from dotenv import load_dotenv
load_dotenv()

from pathlib import Path
import sys
from statistics import median
from datetime import datetime, date
import math
import numpy as np
try:
    from bson import ObjectId
except Exception:
    ObjectId = ()
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.models import PropertyPriceRequest, PriceInfo, AffordabilityRequest, AffordabilityResponse, AffordabilityOption, SourceIngestRequest
from app.services.source_service import search_and_extract, search_historical_prices, collect_from_urls, SourceServiceError
from app.services.storage import ObservationStore
from app.services.ml_service import robust_ppsf
from app.services.location_service import geocode
from app.services.development_service import suitability
from app.unit_utils import to_sqft, from_sqft, convert_price_per_unit, build_equivalents
from app.services.forecast_service import forecast

BASE_DIR=Path(sys._MEIPASS) if getattr(sys,"frozen",False) else Path(__file__).resolve().parents[2]
FRONTEND_DIST=BASE_DIR/"frontend"/"dist"
app=FastAPI(title="LandWise AI Property API",version="5.2.0",description="Evidence-first property price intelligence using Tavily extraction and leakage-free ML.")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])
if (FRONTEND_DIST/"assets").exists(): app.mount("/assets",StaticFiles(directory=FRONTEND_DIST/"assets"),name="assets")
store=ObservationStore()


def _json_safe(value):
    if ObjectId and isinstance(value,ObjectId): return str(value)
    if isinstance(value,(datetime,date)): return value.isoformat()
    if isinstance(value,dict): return {str(k):_json_safe(v) for k,v in value.items() if k!="_id"}
    if isinstance(value,(list,tuple)): return [_json_safe(v) for v in value]
    if isinstance(value,float) and (math.isnan(value) or math.isinf(value)): return None
    return value


def _robust_filter(rows):
    """Reject obvious current-listing outliers before the market estimator."""
    clean = []
    for r in rows:
        try:
            v = float(r.get("canonical_price_per_sqft") or 0)
            if not math.isfinite(v) or v <= 0 or v > 1_000_000:
                continue
            # Values below ₹10/sq ft are almost always parser mistakes for a
            # total price/acre or a non-land number in this product flow.
            if v < 10:
                continue
            if float(r.get("location_match") or 0) < 0.9:
                continue
            clean.append(r)
        except Exception:
            continue
    if len(clean) < 5:
        return clean
    vals = np.asarray([float(r["canonical_price_per_sqft"]) for r in clean], dtype=float)

    # Land prices vary multiplicatively. Filtering in log-space prevents a few
    # very large total-price/area parsing mistakes from stretching the range
    # and the estimator.
    log_vals = np.log(vals)
    med_log = float(np.median(log_vals))
    mad_log = float(np.median(np.abs(log_vals - med_log)))

    if mad_log > 0:
        spread = 3.0 * 1.4826 * mad_log
        lo = max(10.0, math.exp(med_log - spread))
        hi = min(1_000_000.0, math.exp(med_log + spread))
    else:
        lo = max(10.0, float(np.percentile(vals, 10)))
        hi = min(1_000_000.0, float(np.percentile(vals, 90)))
    filtered = [r for r in clean if lo <= float(r["canonical_price_per_sqft"]) <= hi]
    return filtered or clean


def _dedupe(rows):
    out={}
    for r in rows:
        try:
            key=(r.get("source_url"),round(float(r.get("price") or 0),2),round(float(r.get("area") or 0),3),r.get("area_unit"),round(float(r.get("canonical_price_per_sqft") or 0),5))
            out[key]=r
        except Exception:
            continue
    return list(out.values())


@app.get("/health")
async def health(): return {"status":"healthy","version":"5.2.0","ml":"scikit-learn","llm":False}

@app.get("/",include_in_schema=False)
async def root():
    p=FRONTEND_DIST/"index.html"
    return FileResponse(p) if p.exists() else {"status":"ok","message":"Backend running. Build frontend with npm run build."}


async def _collect(req: PropertyPriceRequest):
    """Collect exactly two Tavily searches for a normal price request.

    Search 1 = four completed years of historical land-price evidence.
    Search 2 = current comparable listings.
    The ML forecast is local Python/scikit-learn and consumes zero Tavily credits.
    """
    current_year = datetime.now().year
    historical_years = list(range(current_year - 4, current_year))

    try:
        historical_raw, historical_points = await search_historical_prices(req.location, historical_years)
    except SourceServiceError as e:
        raise HTTPException(502, f"Tavily historical search failed: {e}")

    if req.source_urls:
        current, _ = await collect_from_urls(req.source_urls, req.property_type, req.bhk, req.location)
        discovered = req.source_urls
    else:
        try:
            raw, current = await search_and_extract(req.location, req.property_type, req.bhk, req.property_status)
        except SourceServiceError as e:
            raise HTTPException(502, f"Tavily current search failed: {e}")
        discovered = [r.get("url") for r in raw.get("results", []) if r.get("url")]

    current = _dedupe(current)[:60]
    coords = await geocode(req.location)
    for r in current:
        r["location"] = req.location
        norm_req = "".join(ch.lower() for ch in req.location if ch.isalnum())
        tokens = ["".join(ch.lower() for ch in t if ch.isalnum()) for t in req.location.replace(",", " ").split() if len(t) >= 4]
        ev = "".join(ch.lower() for ch in str(r.get("evidence") or "") if ch.isalnum())
        r["location_match"] = 1.0 if (norm_req and norm_req in ev) or any(t and t in ev for t in tokens) else 0.35
        r["property_type"] = req.property_type if req.property_type != "land" else r.get("property_type", "land")
        r["bhk"] = req.bhk or r.get("bhk")
        try:
            if r.get("area") and r.get("area_unit"):
                r["area_sqft"] = to_sqft(float(r["area"]), r["area_unit"])
        except Exception:
            r["area_sqft"] = None
        if coords:
            r["latitude"] = coords.get("lat"); r["longitude"] = coords.get("lon")
        r["observed_at"] = datetime.now().isoformat()

    # Use ONLY fresh observations from this request for the displayed current
    # market price. Persisting old observations is useful for analytics, but
    # mixing them into today's estimator caused stale/irrelevant prices to
    # dominate the median (e.g. the 31-observation result shown in the UI).
    comparables = _robust_filter(_dedupe(current))
    if current:
        store.insert_many(current)
    return discovered, current, comparables, historical_points, coords, historical_raw


@app.post("/property-price", response_model=PriceInfo)
async def property_price(req: PropertyPriceRequest):
    discovered, current, comparables, historical_points, coords, historical_raw = await _collect(req)
    ppsf = robust_ppsf(comparables)
    forecast_data = forecast_from_dicts(historical_points, req.location)

    unit = req.area_unit or "sq ft"
    price_per_unit = convert_price_per_unit(ppsf, "sq ft", unit) if ppsf is not None else None
    area_sqft = to_sqft(req.area, unit) if req.area else None
    estimated_total = ppsf * area_sqft if (ppsf is not None and area_sqft) else None

    ppsf_values = [float(r["canonical_price_per_sqft"]) for r in comparables if float(r.get("canonical_price_per_sqft") or 0) > 0]
    # "Typical range" should describe the central market evidence, not the
    # single cheapest/most-expensive listing. Use the 10th-90th percentile
    # of the already robust-filtered normalized observations.
    if ppsf_values:
        lo_ppsf, hi_ppsf = np.percentile(np.asarray(ppsf_values, dtype=float), [10, 90])
        if area_sqft:
            min_price = float(lo_ppsf * area_sqft)
            max_price = float(hi_ppsf * area_sqft)
        else:
            min_price = float(lo_ppsf)
            max_price = float(hi_ppsf)
    else:
        min_price = None
        max_price = None

    source_urls = list(dict.fromkeys(r.get("source_url") for r in current if r.get("source_url")))
    source_count = len(source_urls)
    if source_count >= 5 and len(ppsf_values) >= 12:
        confidence = "high"
    elif source_count >= 3 and len(ppsf_values) >= 6:
        confidence = "medium"
    elif ppsf is not None:
        confidence = "low"
    else:
        confidence = "unavailable"

    hist_years = forecast_data.get("historical_years", [])
    hist_points = forecast_data.get("historical_points", [])
    trend = forecast_data.get("trend")
    model_name = forecast_data.get("model")
    if forecast_data.get("status") == "forecast_ready":
        market_trend = f"Historical trend: {trend}; local model forecasts {len(forecast_data.get('forecast', []))} future years."
    else:
        market_trend = "Insufficient dated historical evidence for a forecast."

    response = PriceInfo(
        location=req.location, property_type=req.property_type, bhk=req.bhk, property_status=req.property_status,
        price_per_unit=price_per_unit, unit=unit, currency="INR", estimated_total_price=estimated_total,
        source_summary=(
            f"Two-search evidence pipeline: one Tavily search for dated historical land prices and one Tavily search for current comparable listings. "
            + (f"Current estimate uses {len(comparables)} validated current comparable observations. " if ppsf is not None else "No validated current price/area pair was found; current price is intentionally left unavailable. ")
            + f"Historical ML uses {len(hist_points)} dated observations across years {hist_years or 'not available'}. Forecasting runs locally and uses no additional Tavily request."
        ),
        sources=list(dict.fromkeys(discovered))[:20], source_count=source_count, observation_count=len(comparables), confidence=confidence,
        average_price=estimated_total if area_sqft else (median([float(r["price"]) for r in comparables if r.get("price")]) if comparables else None),
        min_price=min_price, max_price=max_price, average_price_per_sqft=ppsf,
        typical_area_min=min([float(r["area_sqft"]) for r in comparables if r.get("area_sqft")]) if any(r.get("area_sqft") for r in comparables) else None,
        typical_area_max=max([float(r["area_sqft"]) for r in comparables if r.get("area_sqft")]) if any(r.get("area_sqft") for r in comparables) else None,
        sample_size=len(comparables), market_trend=market_trend,
        model_used="current comparable market evidence + local historical time-series forecast",
        ml_metrics={
            "status": forecast_data.get("status"),
            "model": model_name,
            "historical_rows": len(hist_points),
            "historical_years": hist_years,
            "cagr_percent": forecast_data.get("cagr_percent"),
            "log_rmse": forecast_data.get("log_rmse"),
        },
        observations=current[:20],
        historical_data=hist_points,
        forecast=forecast_data.get("forecast", []),
        forecast_model=model_name,
        forecast_trend=trend,
        historical_years=hist_years,
        historical_cagr_percent=forecast_data.get("cagr_percent"),
        historical_yoy_growth_percent=forecast_data.get("historical_yoy_growth_percent", []),
        forecast_yoy_growth_percent=forecast_data.get("forecast_yoy_growth_percent", []),
    )
    return _json_safe(response.model_dump())


def forecast_from_dicts(rows: list[dict], location: str) -> dict:
    from app.services.forecast_service import HistoricalPoint, forecast
    points = [HistoricalPoint(
        year=int(r["year"]),
        price_per_sqft=float(r["price_per_sqft"]),
        location=r.get("location") or location,
        source_domain=r.get("source_domain", ""),
        source_url=r.get("source_url", ""),
        price_type=r.get("price_type", "unknown"),
        evidence=r.get("evidence", ""),
    ) for r in rows if r.get("year") and float(r.get("price_per_sqft") or 0) > 0]
    return forecast(points, horizon=3)


@app.post("/affordability",response_model=AffordabilityResponse)
async def affordability(req: AffordabilityRequest):
    """Budget-based property scenarios.

    Land returns area equivalents.
    Flat/villa/independent-house return 1–5 BHK scenarios without requiring
    a BHK input. Commercial returns usable commercial categories.
    """
    if req.currency.upper() != "INR":
        raise HTTPException(400,"Only INR source normalization is currently enabled.")

    # LAND: answer the question "how much land can I get for this budget?"
    if req.property_type == "land":
        result=PriceInfo.model_validate(await property_price(PropertyPriceRequest(
            property_type="land", location=req.location, area_unit="sq ft", currency="INR"
        )))
        ppsf=float(result.average_price_per_sqft or result.price_per_unit or 0)
        if ppsf<=0:
            raise HTTPException(404,"No usable land price evidence")
        area_sqft=req.budget/ppsf
        equivalents=build_equivalents(ppsf)
        # build_equivalents returns prices; for affordability we need area equivalents.
        area_equivalent={u: from_sqft(area_sqft,u) for u in ["sq ft","sq yd","sq m","acre","hectare","cent","gunta","marla","bigha"]}
        return AffordabilityResponse(
            location=req.location,property_type="land",budget=req.budget,currency="INR",
            price_per_unit=ppsf,unit="sq ft",affordable_area=area_sqft,affordable_area_unit="sq ft",
            equivalent=area_equivalent,property_status=None,
            options=[AffordabilityOption(
                category="land",label="Land / Plot",available=True,
                estimated_price=req.budget,estimated_price_per_sqft=ppsf,
                estimated_area_sqft=area_sqft,estimated_area_display=area_equivalent,
                source_count=result.source_count,observation_count=result.observation_count,
                confidence=result.confidence,
                note="Approximate purchasable land area at the current validated comparable price."
            )],
            notes="For land, the budget is converted into equivalent area at the current validated market price. Taxes, registration, brokerage, development and legal due diligence are excluded.",
            sources=result.sources
        )

    # RESIDENTIAL: no BHK input. Show what the same budget can buy for 1–5 BHK.
    if req.property_type in {"flat","villa","independent_house"}:
        from app.services.source_service import search_affordability_options
        raw, observations = await search_affordability_options(req.location,req.property_type,req.property_status)
        options=[]
        all_sources=[r.get("url") for r in raw.get("results",[]) if r.get("url")]
        for bhk in ["1 BHK","2 BHK","3 BHK","4 BHK","5 BHK"]:
            rows=[r for r in observations if str(r.get("bhk") or "").lower()==bhk.lower() and float(r.get("price") or 0)>0]
            if not rows:
                options.append(AffordabilityOption(category="residential",label=bhk,available=False,property_status=req.property_status,source_count=0,observation_count=0,confidence="low",note="No validated current price evidence was extracted for this BHK in the requested location."))
                continue
            rows=_dedupe(rows)
            area_rows=[r for r in rows if float(r.get("canonical_price_per_sqft") or 0)>0]
            price_only=[r for r in rows if not float(r.get("canonical_price_per_sqft") or 0)>0]
            ppsf=robust_ppsf(area_rows) if area_rows else None
            pricing_rows=area_rows or price_only
            prices=[float(r.get("price") or 0) for r in pricing_rows if r.get("price")]
            total=median(prices) if prices else None
            area_sqft=req.budget/ppsf if ppsf else None
            affordable=bool(total and req.budget>=total)
            note=("Budget appears sufficient for a typical current listing in this BHK segment."
                  if affordable else "Budget is below the typical current asking-price evidence for this BHK segment.")
            if price_only and not area_rows:
                note += " Some current listings expose total price and BHK but not usable area, so affordability is based on total asking-price evidence; price-per-sq-ft is not fabricated."
            options.append(AffordabilityOption(
                category="residential",label=bhk,available=affordable,
                estimated_price=total,estimated_price_per_sqft=ppsf,
                estimated_area_sqft=area_sqft,estimated_area_display={"sq ft":area_sqft} if area_sqft else {},
                property_status=req.property_status,source_count=len(set(r.get("source_url") for r in rows if r.get("source_url"))),
                observation_count=len(rows),confidence="high" if len(rows)>=5 else "medium" if len(rows)>=2 else "low",
                note=note
            ))
        return AffordabilityResponse(
            location=req.location,property_type=req.property_type,budget=req.budget,currency="INR",
            property_status=req.property_status,options=options,
            notes=f"Budget affordability scenarios for {req.property_type.replace('_',' ')} at {req.location}. BHK is not an input; the system compares the same budget against current 1–5 BHK market evidence. Property status is used as a search constraint where source evidence supports it.",
            sources=list(dict.fromkeys(all_sources))[:20]
        )

    # COMMERCIAL: return practical commercial categories rather than BHK.
    if req.property_type == "commercial":
        from app.services.source_service import search_and_extract
        raw, observations = await search_and_extract(req.location,"commercial",None,None)
        observations=_robust_filter(_dedupe(observations))
        # Group broad commercial evidence by keywords in the evidence text.
        categories=[("Office","office"),("Shop","shop"),("Commercial Floor","floor"),("Warehouse","warehouse")]
        options=[]
        for label,keyword in categories:
            rows=[r for r in observations if keyword in str(r.get("evidence") or "").lower()]
            if not rows:
                rows=observations
            ppsf=robust_ppsf(rows) if rows else None
            if not ppsf:
                options.append(AffordabilityOption(category="commercial",label=label,available=False,confidence="low",note="No validated current evidence for this commercial category."))
                continue
            area_sqft=req.budget/ppsf
            options.append(AffordabilityOption(
                category="commercial",label=label,available=True,
                estimated_price=req.budget,estimated_price_per_sqft=ppsf,
                estimated_area_sqft=area_sqft,estimated_area_display={"sq ft":area_sqft},
                source_count=len(set(r.get("source_url") for r in rows if r.get("source_url"))),
                observation_count=len(rows),confidence="high" if len(rows)>=5 else "medium",
                note="Approximate commercial area purchasable at the current validated comparable price; exact configuration depends on listing."
            ))
        return AffordabilityResponse(
            location=req.location,property_type="commercial",budget=req.budget,currency="INR",
            property_status=None,options=options,
            notes="Commercial affordability is shown by practical categories such as office, shop, commercial floor and warehouse. Results are evidence-based estimates, not legal/lease approvals.",
            sources=list(dict.fromkeys(r.get("source_url") for r in observations if r.get("source_url")))[:20]
        )

    raise HTTPException(400,"Unsupported property type for affordability")


@app.post("/ingest-sources")
async def ingest_sources(req: SourceIngestRequest):
    observations,usable=await collect_from_urls(req.urls,req.property_type,req.bhk,req.location)
    coords=await geocode(req.location)
    for r in observations:
        r["location"]=req.location; r["property_type"]=req.property_type; r["bhk"]=req.bhk or r.get("bhk")
        if r.get("area") and r.get("area_unit"):
            try:r["area_sqft"]=to_sqft(float(r["area"]),r["area_unit"])
            except Exception:r["area_sqft"]=None
        if coords:r["latitude"]=coords.get("lat");r["longitude"]=coords.get("lon")
    inserted=store.insert_many(observations)
    return _json_safe({"location":req.location,"inserted":inserted,"usable_sources":usable,"observations":observations})

@app.get("/sources/test")
async def source_test():
    return {"message":"Tavily Search discovers candidate pages; Tavily Extract retrieves selected page content; deterministic parsing creates validated observations. Social/discovery pages are ignored unless they expose structured price + area evidence."}

@app.get("/development-suitability")
async def development_suitability(area:float,unit:str="sq ft",location:str=""):
    sqft=to_sqft(area,unit)
    return {"location":location,"area_sqft":sqft,"disclaimer":"Planning heuristic only; local zoning, setbacks, FAR/FSI, road width and approvals must be checked with the relevant authority.","options":suitability(sqft,"land",location)}
