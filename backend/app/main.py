from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import time
from dotenv import load_dotenv
load_dotenv()

from pathlib import Path
import sys
import asyncio
from app.services import market_cache
from statistics import median
from datetime import datetime, date, timezone, timedelta
import math
import numpy as np
try:
    from bson import ObjectId
except Exception:
    ObjectId = ()
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pymongo.errors import PyMongoError
from app.routers.chat import router as chat_router
from fastapi.staticfiles import StaticFiles

from app.models import (
    PropertyPriceRequest, PriceInfo, AffordabilityRequest, AffordabilityResponse,
    AffordabilityOption, SourceIngestRequest, SignupRequest, LoginRequest,
    AuthResponse, UserPublic, SearchHistoryItem, VerifySignupRequest, ResendOtpRequest,
    ForgotPasswordRequest, ResetPasswordRequest, OtpResponse, PropertyRequest,
)
from app.services.source_service import search_and_extract, collect_from_urls, SourceServiceError
from app.services.storage import ObservationStore
from app.services.user_store import UserStore
from app.services.ml_service import PriceModel, robust_ppsf
from app.services.historical_tavily import tavily_historical_land_prices, forecast_with_ml, HISTORY_PROMPT
from app.services.current_market import current_market_range
from app.services.location_service import geocode
from app.services.development_service import suitability
from app.unit_utils import to_sqft, from_sqft, convert_price_per_unit, build_equivalents
from app.services.email_service import send_otp_email, smtp_configured
from app.auth import hash_password, verify_password, create_access_token, get_current_user, CurrentUser, generate_otp, hash_otp, verify_otp, OTP_EXPIRE_MINUTES, OTP_MAX_ATTEMPTS

BASE_DIR=Path(sys._MEIPASS) if getattr(sys,"frozen",False) else Path(__file__).resolve().parents[2]
FRONTEND_DIST=BASE_DIR/"frontend"/"dist"
app=FastAPI(title="LandWise AI Property API",version="6.0.0",description="Evidence-first property price intelligence using Tavily extraction and leakage-free ML.")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])
if (FRONTEND_DIST/"assets").exists(): app.mount("/assets",StaticFiles(directory=FRONTEND_DIST/"assets"),name="assets")
app.include_router(chat_router, prefix="/chat", tags=["Chat"])

@app.exception_handler(PyMongoError)
async def mongo_error(request, exc):
    return JSONResponse(status_code=503, content={"detail": "MongoDB is unavailable. Please retry after restoring the database connection."})

users=UserStore()
store=ObservationStore(users)
market_collection = users.collection.database["market_rate_cache"] if users.collection is not None else None
if market_collection is not None:
    try:
        market_collection.create_index("expires_at", expireAfterSeconds=0)
    except PyMongoError:
        pass


def _user_public(doc: dict) -> UserPublic:
    return UserPublic(id=doc["_id"], name=doc.get("name",""), email=doc.get("email",""), created_at=doc.get("created_at"))


def _json_safe(value):
    if ObjectId and isinstance(value,ObjectId): return str(value)
    if isinstance(value,(datetime,date)): return value.isoformat()
    if isinstance(value,dict): return {str(k):_json_safe(v) for k,v in value.items() if k!="_id"}
    if isinstance(value,(list,tuple)): return [_json_safe(v) for v in value]
    if isinstance(value,float) and (math.isnan(value) or math.isinf(value)): return None
    return value


def _robust_filter(rows):
    vals=np.array([float(r.get("canonical_price_per_sqft") or 0) for r in rows if float(r.get("canonical_price_per_sqft") or 0)>0],dtype=float)
    if len(vals)<6: return rows
    med=float(np.median(vals)); mad=float(np.median(np.abs(vals-med)))
    if mad>0:
        lo=max(1e-6,med-6*1.4826*mad); hi=med+6*1.4826*mad
    else:
        lo=float(np.percentile(vals,2)); hi=float(np.percentile(vals,98))
    return [r for r in rows if lo<=float(r.get("canonical_price_per_sqft") or 0)<=hi]


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
async def health(): return {"status":"healthy","version":"6.0.0","ml":"scikit-learn","llm":"gemini-chat"}


# ----------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------
async def _issue_otp(user_id: str, email: str, purpose: str):
    if not smtp_configured():
        raise HTTPException(503, "Gmail SMTP is not configured. Add GMAIL_SMTP_USERNAME and GMAIL_SMTP_APP_PASSWORD to backend/.env.")
    otp = generate_otp()
    expires = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRE_MINUTES)
    if not users.set_otp(user_id, hash_otp(otp), expires.isoformat(), purpose):
        raise HTTPException(500, "Could not create OTP challenge.")
    try:
        await asyncio.to_thread(send_otp_email, email, otp, purpose)
    except Exception:
        users.clear_otp(user_id)
        raise HTTPException(502, "Could not send the OTP email. Check Gmail SMTP settings and App Password.")
    return OtpResponse(message="OTP sent to your email address.", email=email, expires_in_seconds=OTP_EXPIRE_MINUTES * 60)


@app.post("/auth/signup", response_model=OtpResponse)
async def signup(req: SignupRequest):
    existing = users.get_by_email(req.email)
    if existing:
        if existing.get("email_verified", True):
            raise HTTPException(409, "An account with this email already exists.")
        # Allow an unfinished signup to request a fresh OTP.
        try:
            hash_password(req.password)
        except ValueError as e:
            raise HTTPException(400, str(e))
        try:
            return await _issue_otp(existing["_id"], existing["email"], "signup")
        except HTTPException:
            raise
    try:
        pw_hash = hash_password(req.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    try:
        doc = users.create_user(req.name, req.email, pw_hash)
    except ValueError as e:
        raise HTTPException(409, str(e))
    try:
        return await _issue_otp(doc["_id"], doc["email"], "signup")
    except HTTPException:
        # Keep the account unverified so the user can retry after configuring SMTP.
        raise


@app.post("/auth/signup/verify", response_model=AuthResponse)
async def verify_signup(req: VerifySignupRequest):
    doc = users.get_by_email(req.email)
    if not doc:
        raise HTTPException(404, "Signup request not found.")
    if doc.get("email_verified", True):
        raise HTTPException(400, "Email is already verified. Please log in.")
    state = users.get_otp_state(doc["_id"]) or {}
    if state.get("otp_purpose") != "signup" or not state.get("otp_hash"):
        raise HTTPException(400, "No active signup OTP. Request a new code.")
    try:
        expires = datetime.fromisoformat(state["otp_expires_at"])
    except Exception:
        expires = datetime.now(timezone.utc) - timedelta(seconds=1)
    if expires <= datetime.now(timezone.utc):
        users.clear_otp(doc["_id"])
        raise HTTPException(400, "OTP expired. Request a new code.")
    attempts = int(state.get("otp_attempts") or 0)
    if attempts >= OTP_MAX_ATTEMPTS:
        users.clear_otp(doc["_id"])
        raise HTTPException(429, "Too many incorrect OTP attempts. Request a new code.")
    if not verify_otp(req.otp, state["otp_hash"]):
        users.increment_otp_attempts(doc["_id"])
        raise HTTPException(400, "Invalid OTP.")
    users.mark_email_verified(doc["_id"])
    users.clear_otp(doc["_id"])
    doc = users.get_by_id(doc["_id"]) or doc
    token = create_access_token(doc["_id"], doc["email"])
    return AuthResponse(token=token, user=_user_public(doc))


@app.post("/auth/otp/resend", response_model=OtpResponse)
async def resend_otp(req: ResendOtpRequest):
    doc = users.get_by_email(req.email)
    if not doc:
        # Do not reveal account existence for password-reset flows.
        if req.purpose == "reset":
            return OtpResponse(message="If the email is registered, a reset OTP has been sent.", email=req.email)
        raise HTTPException(404, "Signup request not found.")
    if req.purpose == "signup" and doc.get("email_verified", True):
        raise HTTPException(400, "Email is already verified. Please log in.")
    if req.purpose == "reset" and not doc.get("email_verified", True):
        raise HTTPException(400, "Please verify your email before resetting the password.")
    return await _issue_otp(doc["_id"], doc["email"], req.purpose)


@app.post("/auth/forgot-password", response_model=OtpResponse)
async def forgot_password(req: ForgotPasswordRequest):
    doc = users.get_by_email(req.email)
    if not doc or not doc.get("email_verified", True):
        return OtpResponse(message="If the email is registered, a reset OTP has been sent.", email=req.email)
    return await _issue_otp(doc["_id"], doc["email"], "reset")


@app.post("/auth/reset-password")
async def reset_password(req: ResetPasswordRequest):
    doc = users.get_by_email(req.email)
    if not doc:
        raise HTTPException(400, "Invalid reset request.")
    state = users.get_otp_state(doc["_id"]) or {}
    if state.get("otp_purpose") != "reset" or not state.get("otp_hash"):
        raise HTTPException(400, "No active reset OTP. Request a new code.")
    try:
        expires = datetime.fromisoformat(state["otp_expires_at"])
    except Exception:
        expires = datetime.now(timezone.utc) - timedelta(seconds=1)
    if expires <= datetime.now(timezone.utc):
        users.clear_otp(doc["_id"])
        raise HTTPException(400, "OTP expired. Request a new code.")
    attempts = int(state.get("otp_attempts") or 0)
    if attempts >= OTP_MAX_ATTEMPTS:
        users.clear_otp(doc["_id"])
        raise HTTPException(429, "Too many incorrect OTP attempts. Request a new code.")
    if not verify_otp(req.otp, state["otp_hash"]):
        users.increment_otp_attempts(doc["_id"])
        raise HTTPException(400, "Invalid OTP.")
    try:
        pw_hash = hash_password(req.new_password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    users.update_password(doc["_id"], pw_hash)
    users.clear_otp(doc["_id"])
    return {"message": "Password reset successfully. You can now log in."}


@app.post("/auth/login", response_model=AuthResponse)
async def login(req: LoginRequest):
    doc = users.get_by_email(req.email)
    if not doc or not verify_password(req.password, doc.get("password_hash", "")):
        raise HTTPException(401, "Incorrect email or password.")
    # Existing pre-OTP accounts are treated as verified for backwards compatibility.
    if not doc.get("email_verified", True):
        raise HTTPException(403, "Please verify your email with the OTP sent during signup.")
    token = create_access_token(doc["_id"], doc["email"])
    return AuthResponse(token=token, user=_user_public(doc))

@app.get("/auth/me",response_model=UserPublic)
async def me(current: CurrentUser = Depends(get_current_user)):
    doc=users.get_by_id(current.user_id)
    if not doc: raise HTTPException(401,"Account no longer exists.")
    return _user_public(doc)

@app.get("/auth/history",response_model=list[SearchHistoryItem])
async def history(limit:int=50, current: CurrentUser = Depends(get_current_user)):
    rows=users.get_history(current.user_id,limit=limit)
    return [SearchHistoryItem(id=r.get("id"),type=r.get("type"),request=r.get("request") or {},response=r.get("response") or {},created_at=r.get("created_at")) for r in rows]

@app.delete("/auth/history/{item_id}")
async def delete_history(item_id:str, current: CurrentUser = Depends(get_current_user)):
    ok=users.delete_history_item(current.user_id,item_id)
    if not ok: raise HTTPException(404,"History item not found.")
    return {"deleted":True}

@app.get("/",include_in_schema=False)
async def root():
    p=FRONTEND_DIST/"index.html"
    return FileResponse(p) if p.exists() else {"status":"ok","message":"Backend running. Build frontend with npm run build."}


async def _collect(req: PropertyPriceRequest):
    # Geocoding is independent of market evidence collection.
    geocode_task = asyncio.create_task(geocode(req.location))
    try:
        return await _collect_with_geocode(req, geocode_task)
    finally:
        if not geocode_task.done():
            geocode_task.cancel()


async def _collect_with_geocode(req: PropertyPriceRequest, geocode_task):
    if req.source_urls:
        current,_=await collect_from_urls(req.source_urls,req.property_type,req.bhk,req.location)
        discovered=req.source_urls
    else:
        try:
            raw,current=await search_and_extract(req.location,req.property_type,req.bhk,req.property_status)
        except SourceServiceError as e:
            raise HTTPException(502,f"Tavily search failed: {e}")
        discovered=[r.get("url") for r in raw.get("results",[]) if r.get("url")]

    current=_dedupe(current)[:60]
    coords=await geocode_task
    for r in current:
        r["location"]=req.location
        # Prefer observations whose evidence actually names the requested locality.
        # This matters for city/mandal pages that contain many neighboring localities.
        norm_req="".join(ch.lower() for ch in req.location if ch.isalnum())
        tokens=["".join(ch.lower() for ch in t if ch.isalnum()) for t in req.location.replace(","," ").split() if len(t)>=4]
        ev="".join(ch.lower() for ch in str(r.get("evidence") or "") if ch.isalnum())
        r["location_match"]=1.0 if (norm_req and norm_req in ev) or any(t and t in ev for t in tokens) else 0.35
        r["property_type"]=req.property_type if req.property_type!="land" else r.get("property_type","land")
        r["bhk"]=req.bhk or r.get("bhk")
        try:
            if r.get("area") and r.get("area_unit"):
                r["area_sqft"]=to_sqft(float(r["area"]),r["area_unit"])
        except Exception:
            r["area_sqft"]=None
        if coords:
            r["latitude"]=coords.get("lat"); r["longitude"]=coords.get("lon")
        r["observed_at"]=datetime.now().isoformat()

    # Real-time comparable set: current evidence + previously stored evidence for this locality.
    previous=store.find(req.location,req.property_type,req.bhk,limit=250)
    previous_keys={(r.get("source_url"),round(float(r.get("price") or 0),2),round(float(r.get("area") or 0),3)) for r in current}
    previous=[r for r in previous if (r.get("source_url"),round(float(r.get("price") or 0),2),round(float(r.get("area") or 0),3)) not in previous_keys]
    comparables=_robust_filter(_dedupe(current+previous)[:300])

    # Current observations are persisted later, embedded into the requesting
    # user's own search-history entry (see user_store.add_search_history),
    # not into a separate collection. They become future historical rows the
    # next time any user searches a nearby location.
    for r in current:
        r.setdefault("stored_at",datetime.now(timezone.utc).isoformat())

    # ML training is strictly historical and never uses the current Tavily target as a feature.
    historical=store.all(req.property_type,req.bhk,limit=10000)
    current_keys={(r.get("source_url"),round(float(r.get("price") or 0),2),round(float(r.get("area") or 0),3)) for r in current}
    historical=[r for r in historical if (r.get("source_url"),round(float(r.get("price") or 0),2),round(float(r.get("area") or 0),3)) not in current_keys]
    return discovered,current,comparables,historical,coords


@app.post("/property-price", response_model=PriceInfo)
async def property_price(
    req: PropertyPriceRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    # --------------------------------------------------------
    # Start total request timer
    # --------------------------------------------------------
    start_time = time.perf_counter()

    print("\n==========================================")
    print("        LANDWISE REQUEST STARTED")
    print("==========================================")
    print(f"Location      : {req.location}")
    print(f"Property Type : {req.property_type}")
    print("==========================================\n")

    # key = market_cache.cache_key(req)
    # if key is not None and market_collection is not None:
    #     cached = await asyncio.to_thread(market_cache.get, market_collection, key)
    #     if cached:
    #         safe = _json_safe(market_cache.for_area(cached, req))
    #         search_id = await asyncio.to_thread(users.add_search_history, current_user.user_id, {
    #             "type": "property_price", "request": _json_safe(req.model_dump()),
    #             "response": safe, "observations": cached.get("observations", []),
    #         })
    #         safe["search_id"] = search_id
    #         print(f"LANDWISE CACHE HIT: {req.location}; {time.perf_counter()-start_time:.2f}s")
    #         return safe

    
    # Check reusable market-rate cache
    cache_start = time.perf_counter()
    key = market_cache.cache_key(req)

    print(f"[CACHE] Location: {req.location}")
    print(f"[CACHE] Property type: {req.property_type}")
    print(f"[CACHE] Key: {key!r}")

    if key is None:
        print("[CACHE] SKIPPED: Cache key unavailable")

    elif market_collection is None:
        print("[CACHE] SKIPPED: MongoDB collection unavailable")

    else:
        cached = await asyncio.to_thread(
            market_cache.get,
            market_collection,
            key
        )

        cache_ms = (time.perf_counter() - cache_start) * 1000

        if cached is not None:
            print(f"[CACHE] HIT | Lookup: {cache_ms:.1f} ms")

            safe = _json_safe(
                market_cache.for_area(cached, req)
            )

            search_id = await asyncio.to_thread(
                users.add_search_history,
                current_user.user_id,
                {
                    "type": "property_price",
                    "request": _json_safe(req.model_dump()),
                    "response": safe,
                    "observations": cached.get("observations", []),
                }
            )

            safe["search_id"] = search_id

            print(
                f"[CACHE] Returned in "
                f"{time.perf_counter() - start_time:.2f}s"
            )

            return safe

        print(f"[CACHE] MISS | Lookup: {cache_ms:.1f} ms")

    print("[TAVILY] Cache unavailable; starting fresh searches")


    # Start independent market/history lookups while source evidence is collected.
    market_task = history_task = None
    if req.property_type == "land":
        market_task = asyncio.create_task(current_market_range(req.location))
        history_task = asyncio.create_task(tavily_historical_land_prices(req.location))
    try:
        discovered, current, comparables, historical, coords = await _collect(req)
    except BaseException:
        for task in (market_task, history_task):
            if task is not None:
                task.cancel()
        if market_task is not None:
            await asyncio.gather(market_task, history_task, return_exceptions=True)
        raise
    ppsf=robust_ppsf(comparables)
    if ppsf is None:
        for task in (market_task, history_task):
            if task is not None:
                task.cancel()
        if market_task is not None:
            await asyncio.gather(market_task, history_task, return_exceptions=True)
        raise HTTPException(404,"No valid property price + area evidence was extracted from the current sources. Tavily may have returned blocked/generic pages or snippets without an explicit price-and-area pair. The system will not guess a price.")

    # Land history is retrieved independently from Tavily using the exact
    # requested year-wise prompt. Google Search/AI Overview is not part of this
    # pipeline. The four annual values feed a dedicated small-sample ML model.
    historical_prices=[]
    forecast_prices=[]
    current_market={}
    forecast_metrics={}
    historical_sources=[]
    history_prompt=None

    
    if req.property_type == "land":

        # ------------------------------------------------------------
        # Run independent Tavily operations in parallel.
        #
        # Before:
        #   current market -> wait -> historical -> ML
        #
        # Now:
        #   current market ─────┐
        #                       ├── run together
        #   historical ─────────┘
        #
        # This reduces the waiting time from:
        #   current_time + historical_time
        #
        # to approximately:
        #   max(current_time, historical_time)
        # ------------------------------------------------------------

        current_market_result, history_result = await asyncio.gather(
            market_task, history_task, return_exceptions=True
        )

        # ------------------------------------------------------------
        # Current market result
        # ------------------------------------------------------------

        if isinstance(current_market_result, Exception):

            if isinstance(current_market_result, SourceServiceError):
                current_market = {
                    "status": "unavailable",
                    "error": str(current_market_result)
                }
            else:
                current_market = {
                    "status": "unavailable",
                    "error": str(current_market_result)
                }

        else:
            current_market = current_market_result or {}

        # ------------------------------------------------------------
        # Historical result
        # ------------------------------------------------------------

        if isinstance(history_result, Exception):

            if isinstance(history_result, SourceServiceError):
                forecast_metrics = {
                    "status": "tavily_failed",
                    "error": str(history_result)
                }
            else:
                forecast_metrics = {
                    "status": "historical_pipeline_failed",
                    "error": str(history_result)
                }

        else:

            history_data = history_result or {}

            historical_prices = (
                history_data.get("historical_prices") or []
            )

            # ML forecasting happens only after historical data arrives.
            forecast_prices, forecast_metrics = forecast_with_ml(
                historical_prices,
                horizon=5
            )

            historical_sources = (
                history_data.get("sources") or []
            )

            history_prompt = (
                history_data.get("query")
                or HISTORY_PROMPT.format(
                    Location=req.location
                )
            )

    # Keep the existing cross-location model for non-land property types. For
    # land, the dedicated four-year Tavily time series is the ML forecast and
    # must not change the current comparable price.
    model=PriceModel(); model.fit(historical)
    if req.property_type == "land":
        final_ppsf=ppsf
        if forecast_metrics.get("status")=="trained":
            model_used=f"Tavily current comparable evidence + {forecast_metrics.get('algorithm')} historical forecast"
        else:
            model_used=f"Tavily current comparable evidence + historical ML unavailable ({forecast_metrics.get('status','unknown')})"
    else:
        ml_ppsf=None
        if coords and req.area:
            try:
                ml_ppsf=model.predict(area_sqft=to_sqft(req.area,req.area_unit or "sq ft"),latitude=coords.get("lat",0),longitude=coords.get("lon",0),source_quality=float(np.mean([float(r.get("source_quality") or .5) for r in current])) if current else .5,property_type=req.property_type,bhk=req.bhk)
            except Exception:
                ml_ppsf=None

        r2=model.metrics.get("r2") if isinstance(model.metrics,dict) else None
        mape=model.metrics.get("mape") if isinstance(model.metrics,dict) else None
        ml_is_trustworthy=(model.metrics.get("status")=="trained" and r2 is not None and r2>0.15 and (mape is None or mape<0.45))
        if ml_ppsf is not None and ml_is_trustworthy:
            ml_ppsf_clamped=min(max(ml_ppsf,ppsf*0.5),ppsf*2.0)
            weight=max(0.05,min(0.3,r2*0.35))
            final_ppsf=(1-weight)*ppsf+weight*ml_ppsf_clamped
            model_used=f"current comparable market evidence + {round(weight*100)}% historical ML correction (validated R²={r2:.2f}, MAPE={mape:.1%})" if mape is not None else f"current comparable market evidence + {round(weight*100)}% historical ML correction (validated R²={r2:.2f})"
        else:
            final_ppsf=ppsf
            reason="insufficient independent historical data" if model.metrics.get("status")!="trained" else "the trained model did not pass validation accuracy checks"
            model_used=f"current comparable market evidence (ML not used: {reason})"

    unit=req.area_unit or "sq ft"
    price_per_unit=convert_price_per_unit(final_ppsf,"sq ft",unit)
    area_sqft=to_sqft(req.area,unit) if req.area else None
    estimated_total=final_ppsf*area_sqft if area_sqft else None

    ppsf_values=[float(r["canonical_price_per_sqft"]) for r in comparables if float(r.get("canonical_price_per_sqft") or 0)>0]
    # Typical range for land is sourced from a dedicated, current-location Tavily
    # market query. It must not be derived from arbitrary stored observations:
    # stale/neighboring listings were the reason the dashboard previously showed
    # values such as ₹0 or implausibly wide ranges.
    market_min=float(current_market.get("min_price_per_sqft") or 0) if current_market else 0
    market_max=float(current_market.get("max_price_per_sqft") or 0) if current_market else 0
    has_market_range=(req.property_type == "land" and market_min > 0 and market_max >= market_min)
    # ============================================================
    # FINAL ESTIMATED RATE
    # ============================================================
    # Never force the estimate to the minimum/maximum.
    # If the calculated estimate is exactly the minimum or falls outside
    # the displayed Typical Price Range, use the midpoint of that range.
    # Values strictly inside the range remain unchanged.
    # ============================================================
    if has_market_range:
        market_min = float(market_min)
        market_max = float(market_max)
        final_ppsf = float(final_ppsf)

        if market_min > market_max:
            market_min, market_max = market_max, market_min

        typical_midpoint = (market_min + market_max) / 2.0

        # If the calculated estimate lands exactly on the minimum,
        # do not present the minimum as the Estimated Rate. Use the
        # midpoint of the Typical Price Range instead. Values strictly
        # inside the range remain unchanged; values above the maximum
        # also fall back to the midpoint.
        if final_ppsf <= market_min or final_ppsf > market_max:
            final_ppsf = typical_midpoint

    elif ppsf_values:
        # Non-land properties use their comparable-evidence range.
        comparable_min = float(min(ppsf_values))
        comparable_max = float(max(ppsf_values))
        final_ppsf = float(final_ppsf)

        if comparable_min > comparable_max:
            comparable_min, comparable_max = comparable_max, comparable_min

        comparable_midpoint = (comparable_min + comparable_max) / 2.0

        if final_ppsf < comparable_min or final_ppsf > comparable_max:
            final_ppsf = comparable_midpoint

    # Recalculate all dependent values from the corrected final rate.
    price_per_unit = convert_price_per_unit(final_ppsf,"sq ft",unit)
    estimated_total = final_ppsf * area_sqft if area_sqft else estimated_total

    # Anchor the five-year forecast to the final displayed estimated rate.
    # The ML forecast keeps its year-to-year growth pattern, but its first
    # forecast point is scaled from the same corrected rate shown in the card.
    if req.property_type == "land" and forecast_prices and final_ppsf > 0:
        first_forecast = float(
            forecast_prices[0].get("predicted_price_per_sqft") or 0
        )
        if first_forecast > 0:
            forecast_scale = final_ppsf / first_forecast
            for forecast_row in forecast_prices:
                for key in (
                    "predicted_price_per_sqft",
                    "min_price_per_sqft",
                    "max_price_per_sqft",
                ):
                    value = forecast_row.get(key)
                    if value is not None:
                        forecast_row[key] = round(
                            float(value) * forecast_scale,
                            2
                        )
            forecast_metrics["forecast_anchor_ppsf"] = round(final_ppsf, 2)
            forecast_metrics["forecast_anchor_rule"] = (
                "Forecast trend is scaled to the final estimated rate; "
                "the ML year-to-year growth pattern is preserved."
            )
    # min/max_price remain total-price bounds for the requested area.
    # IMPORTANT: typical_price_min/max are always returned in the canonical
    # normalized unit ₹/sq ft. The frontend converts this canonical range
    # exactly once when the user changes PRICE UNIT. Returning an already
    # converted value here caused double-conversion bugs (for example an
    # acre range being multiplied by 43,560 again when switching to sq ft).
    if area_sqft:
        comparable_totals=[v*area_sqft for v in ppsf_values]
        min_price=min(comparable_totals) if comparable_totals else None
        max_price=max(comparable_totals) if comparable_totals else None
    else:
        totals=[float(r["price"]) for r in comparables if r.get("price")]
        min_price=min(totals) if totals else None; max_price=max(totals) if totals else None
    typical_base_min = market_min if has_market_range else (min(ppsf_values) if ppsf_values else None)
    typical_base_max = market_max if has_market_range else (max(ppsf_values) if ppsf_values else None)
    # Canonical API contract: typical range is ALWAYS ₹/sq ft.
    # Do not convert it to req.area_unit here; the UI owns presentation-unit
    # conversion so a unit dropdown change cannot apply the conversion twice.
    typical_price_min = typical_base_min
    typical_price_max = typical_base_max
    source_urls=list(dict.fromkeys(r.get("source_url") for r in current if r.get("source_url")))
    source_count=len(source_urls)
    unique_values=len({round(v,2) for v in ppsf_values})
    if source_count>=5 and len(ppsf_values)>=12: confidence="high"
    elif source_count>=3 and len(ppsf_values)>=6: confidence="medium"
    else: confidence="low"

    response=PriceInfo(
        location=req.location,property_type=req.property_type,bhk=req.bhk,property_status=req.property_status,
        price_per_unit=price_per_unit,unit=unit,currency="INR",estimated_total_price=estimated_total,
        source_summary=(f"Validated {len(current)} current observations from {source_count} usable Tavily sources. "
                        f"The primary estimate is the weighted median of normalized current comparable prices. "
                        + (f"The Typical Price Range comes from a dedicated current-location market search ({current_market.get('status','unavailable')}) using current property-market sources." if req.property_type == "land" else "")
                        + (f" The exact Tavily history prompt returned {len(historical_prices)} annual points for the dedicated ML forecast." if req.property_type == "land" else f" {len(historical)} stored historical observations are available for the generic property model.")),
        sources=list(dict.fromkeys(discovered + historical_sources + (current_market.get("sources") or [])))[:20],source_count=len(set(discovered + historical_sources + (current_market.get("sources") or []))),observation_count=len(comparables),confidence=confidence,
        average_price=estimated_total if area_sqft else (median([float(r["price"]) for r in comparables if r.get("price")]) if comparables else None),
        min_price=min_price,max_price=max_price,average_price_per_sqft=final_ppsf,
        typical_price_min=typical_price_min,typical_price_max=typical_price_max,
        typical_price_unit="sq ft",
        typical_price_source_type=(current_market.get("status") if req.property_type == "land" else "current_comparables"),
        typical_price_sources=(current_market.get("sources") or []) if req.property_type == "land" else [],
        typical_area_min=min([float(r["area_sqft"]) for r in comparables if r.get("area_sqft")]) if any(r.get("area_sqft") for r in comparables) else None,
        typical_area_max=max([float(r["area_sqft"]) for r in comparables if r.get("area_sqft")]) if any(r.get("area_sqft") for r in comparables) else None,
        sample_size=len(comparables),
        market_trend=(f"{len(historical_prices)} completed annual Tavily observations; ML forecast generated" if req.property_type == "land" and forecast_prices else ("Historical ML observations available" if len(historical)>=30 else "Not enough time-series data for a trend")),
        model_used=model_used,
        ml_metrics=(forecast_metrics if req.property_type == "land" else model.metrics),
        observations=current[:20],
        historical_prices=historical_prices,
        forecast_prices=forecast_prices,
        historical_query=history_prompt,
        historical_sources=historical_sources
    )
    safe=_json_safe(response.model_dump())
    if key is not None and market_collection is not None and safe.get("average_price_per_sqft"):
        try:
            await asyncio.to_thread(market_cache.put, market_collection, key, safe)
        except PyMongoError:
            pass  # Cache is an optimization, never a requirement for estimates.
    search_id=users.add_search_history(current_user.user_id,{
        "type":"property_price",
        "request":_json_safe(req.model_dump()),
        "response":safe,
        "observations":_json_safe(current),
    })
    # safe["search_id"]=search_id
    # return safe
    # --------------------------------------------------------
    # Calculate total request processing time
    # --------------------------------------------------------
    total_time = time.perf_counter() - start_time

    # --------------------------------------------------------
    # Print performance information in backend terminal
    # --------------------------------------------------------
    print("\n==========================================")
    print("        LANDWISE REQUEST PERFORMANCE")
    print("==========================================")
    print(f"Location      : {req.location}")
    print(f"Property Type : {req.property_type}")
    print(f"Total Time    : {total_time:.2f} seconds")
    print(f"Total Time    : {total_time * 1000:.0f} ms")
    print("==========================================\n")

    safe["search_id"] = search_id

    return safe



def _log_affordability(current_user: CurrentUser, req: "AffordabilityRequest", resp: AffordabilityResponse):
    resp.search_id=users.add_search_history(current_user.user_id,{
        "type":"affordability",
        "request":_json_safe(req.model_dump()),
        "response":_json_safe(resp.model_dump()),
    })



# @app.post("/affordability",response_model=AffordabilityResponse)
# async def affordability(req: AffordabilityRequest, current_user: CurrentUser = Depends(get_current_user)):
#     """Budget-based property scenarios.

#     Land returns area equivalents.
#     Flat/villa/independent-house return 1–5 BHK scenarios without requiring
#     a BHK input. Commercial returns usable commercial categories.
#     """
#     if req.currency.upper() != "INR":
#         raise HTTPException(400,"Only INR source normalization is currently enabled.")

#     # LAND: answer the question "how much land can I get for this budget?"
#     if req.property_type == "land":
#         result=PriceInfo.model_validate(await property_price(PropertyPriceRequest(
#             property_type="land", location=req.location, area_unit="sq ft", currency="INR"
#         ), current_user))
#         ppsf=float(result.average_price_per_sqft or result.price_per_unit or 0)
#         if ppsf<=0:
#             raise HTTPException(404,"No usable land price evidence")
#         area_sqft=req.budget/ppsf
#         equivalents=build_equivalents(ppsf)
#         # build_equivalents returns prices; for affordability we need area equivalents.
#         area_equivalent={u: from_sqft(area_sqft,u) for u in ["sq ft","sq yd","sq m","acre","hectare","cent","gunta","marla","bigha"]}
#         resp=AffordabilityResponse(
#             location=req.location,property_type="land",budget=req.budget,currency="INR",
#             price_per_unit=ppsf,unit="sq ft",affordable_area=area_sqft,affordable_area_unit="sq ft",
#             equivalent=area_equivalent,property_status=None,
#             options=[AffordabilityOption(
#                 category="land",label="Land / Plot",available=True,
#                 estimated_price=req.budget,estimated_price_per_sqft=ppsf,
#                 estimated_area_sqft=area_sqft,estimated_area_display=area_equivalent,
#                 source_count=result.source_count,observation_count=result.observation_count,
#                 confidence=result.confidence,
#                 note="Approximate purchasable land area at the current validated comparable price."
#             )],
#             notes="For land, the budget is converted into equivalent area at the current validated market price. Taxes, registration, brokerage, development and legal due diligence are excluded.",
#             sources=result.sources
#         )
#         _log_affordability(current_user,req,resp)
#         return resp

#     # RESIDENTIAL: no BHK input. Show what the same budget can buy for 1–5 BHK.
#     if req.property_type in {"flat","villa","independent_house"}:
#         from app.services.source_service import search_affordability_options
#         raw, observations = await search_affordability_options(req.location,req.property_type,req.property_status)
#         options=[]
#         all_sources=[r.get("url") for r in raw.get("results",[]) if r.get("url")]
#         for bhk in ["1 BHK","2 BHK","3 BHK","4 BHK","5 BHK"]:
#             rows=[r for r in observations if str(r.get("bhk") or "").lower()==bhk.lower() and float(r.get("price") or 0)>0]
#             if not rows:
#                 options.append(AffordabilityOption(category="residential",label=bhk,available=False,property_status=req.property_status,source_count=0,observation_count=0,confidence="low",note="No validated current price evidence was extracted for this BHK in the requested location."))
#                 continue
#             rows=_dedupe(rows)
#             area_rows=[r for r in rows if float(r.get("canonical_price_per_sqft") or 0)>0]
#             price_only=[r for r in rows if not float(r.get("canonical_price_per_sqft") or 0)>0]
#             ppsf=robust_ppsf(area_rows) if area_rows else None
#             pricing_rows=area_rows or price_only
#             prices=[float(r.get("price") or 0) for r in pricing_rows if r.get("price")]
#             total=median(prices) if prices else None
#             area_sqft=req.budget/ppsf if ppsf else None
#             affordable=bool(total and req.budget>=total)
#             note=("Budget appears sufficient for a typical current listing in this BHK segment."
#                   if affordable else "Budget is below the typical current asking-price evidence for this BHK segment.")
#             if price_only and not area_rows:
#                 note += " Some current listings expose total price and BHK but not usable area, so affordability is based on total asking-price evidence; price-per-sq-ft is not fabricated."
#             options.append(AffordabilityOption(
#                 category="residential",label=bhk,available=affordable,
#                 estimated_price=total,estimated_price_per_sqft=ppsf,
#                 estimated_area_sqft=area_sqft,estimated_area_display={"sq ft":area_sqft} if area_sqft else {},
#                 property_status=req.property_status,source_count=len(set(r.get("source_url") for r in rows if r.get("source_url"))),
#                 observation_count=len(rows),confidence="high" if len(rows)>=5 else "medium" if len(rows)>=2 else "low",
#                 note=note
#             ))
#         resp=AffordabilityResponse(
#             location=req.location,property_type=req.property_type,budget=req.budget,currency="INR",
#             property_status=req.property_status,options=options,
#             notes=f"Budget affordability scenarios for {req.property_type.replace('_',' ')} at {req.location}. BHK is not an input; the system compares the same budget against current 1–5 BHK market evidence. Property status is used as a search constraint where source evidence supports it.",
#             sources=list(dict.fromkeys(all_sources))[:20]
#         )
#         _log_affordability(current_user,req,resp)
#         return resp

#     # COMMERCIAL: return practical commercial categories rather than BHK.
#     if req.property_type == "commercial":
#         from app.services.source_service import search_and_extract
#         raw, observations = await search_and_extract(req.location,"commercial",None,None)
#         observations=_robust_filter(_dedupe(observations))
#         # Group broad commercial evidence by keywords in the evidence text.
#         categories=[("Office","office"),("Shop","shop"),("Commercial Floor","floor"),("Warehouse","warehouse")]
#         options=[]
#         for label,keyword in categories:
#             rows=[r for r in observations if keyword in str(r.get("evidence") or "").lower()]
#             if not rows:
#                 rows=observations
#             ppsf=robust_ppsf(rows) if rows else None
#             if not ppsf:
#                 options.append(AffordabilityOption(category="commercial",label=label,available=False,confidence="low",note="No validated current evidence for this commercial category."))
#                 continue
#             area_sqft=req.budget/ppsf
#             options.append(AffordabilityOption(
#                 category="commercial",label=label,available=True,
#                 estimated_price=req.budget,estimated_price_per_sqft=ppsf,
#                 estimated_area_sqft=area_sqft,estimated_area_display={"sq ft":area_sqft},
#                 source_count=len(set(r.get("source_url") for r in rows if r.get("source_url"))),
#                 observation_count=len(rows),confidence="high" if len(rows)>=5 else "medium",
#                 note="Approximate commercial area purchasable at the current validated comparable price; exact configuration depends on listing."
#             ))
#         resp=AffordabilityResponse(
#             location=req.location,property_type="commercial",budget=req.budget,currency="INR",
#             property_status=None,options=options,
#             notes="Commercial affordability is shown by practical categories such as office, shop, commercial floor and warehouse. Results are evidence-based estimates, not legal/lease approvals.",
#             sources=list(dict.fromkeys(r.get("source_url") for r in observations if r.get("source_url")))[:20]
#         )
#         _log_affordability(current_user,req,resp)
#         return resp

#     raise HTTPException(400,"Unsupported property type for affordability")



@app.post("/affordability", response_model=AffordabilityResponse)
async def affordability(
    req: AffordabilityRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Budget-based property affordability scenarios.

    LAND:
        Converts the user's budget into purchasable land area.

    RESIDENTIAL:
        Compares the same budget against 1–5 BHK market evidence.

    COMMERCIAL:
        Compares the budget across Office, Shop, Floor and Warehouse.

    All price calculations use validated market evidence.
    No price-per-sq-ft value is fabricated when usable evidence is unavailable.
    """

    # ------------------------------------------------------------
    # Basic request validation
    # ------------------------------------------------------------
    property_type = str(req.property_type or "").strip().lower()
    location = str(req.location or "").strip()
    currency = str(req.currency or "INR").strip().upper()
    budget = float(req.budget or 0)

    if not location:
        raise HTTPException(
            status_code=400,
            detail="Location is required."
        )

    if budget <= 0:
        raise HTTPException(
            status_code=400,
            detail="Budget must be greater than 0."
        )

    if currency != "INR":
        raise HTTPException(
            status_code=400,
            detail="Only INR source normalization is currently enabled."
        )

    # ============================================================
    # LAND
    # ============================================================
    if property_type == "land":

        result = PriceInfo.model_validate(
            await property_price(
                PropertyPriceRequest(
                    property_type="land",
                    location=location,
                    area_unit="sq ft",
                    currency="INR"
                ),
                current_user
            )
        )

        ppsf = float(
            result.average_price_per_sqft
            or result.price_per_unit
            or 0
        )

        if ppsf <= 0:
            raise HTTPException(
                status_code=404,
                detail="No usable land price evidence was found."
            )

        # Budget / ₹ per sq.ft = affordable area in sq.ft
        area_sqft = budget / ppsf

        # Convert the affordable area into different land units.
        area_equivalent = {
            unit: from_sqft(area_sqft, unit)
            for unit in [
                "sq ft",
                "sq yd",
                "sq m",
                "acre",
                "hectare",
                "cent",
                "gunta",
                "marla",
                "bigha"
            ]
        }

        resp = AffordabilityResponse(
            location=location,
            property_type="land",
            budget=budget,
            currency="INR",

            price_per_unit=ppsf,
            unit="sq ft",

            affordable_area=area_sqft,
            affordable_area_unit="sq ft",

            equivalent=area_equivalent,

            property_status=None,

            options=[
                AffordabilityOption(
                    category="land",
                    label="Land / Plot",
                    available=True,

                    estimated_price=budget,
                    estimated_price_per_sqft=ppsf,

                    estimated_area_sqft=area_sqft,
                    estimated_area_display=area_equivalent,

                    source_count=result.source_count,
                    observation_count=result.observation_count,
                    confidence=result.confidence,

                    note=(
                        "Approximate purchasable land area at the current "
                        "validated comparable price."
                    )
                )
            ],

            notes=(
                "For land, the budget is converted into equivalent area "
                "at the current validated market price. Taxes, registration, "
                "brokerage, development and legal due diligence are excluded."
            ),

            sources=result.sources
        )

        _log_affordability(
            current_user,
            req,
            resp
        )

        return resp

    # ============================================================
    # RESIDENTIAL
    # ============================================================
    if property_type in {
        "flat",
        "villa",
        "independent_house"
    }:

        from app.services.source_service import search_affordability_options

        property_status = getattr(
            req,
            "property_status",
            None
        )

        raw, observations = await search_affordability_options(
            location,
            property_type,
            property_status
        )

        options = []

        all_sources = [
            r.get("url")
            for r in raw.get("results", [])
            if r.get("url")
        ]

        # --------------------------------------------------------
        # Compare budget against 1–5 BHK
        # --------------------------------------------------------
        for bhk in [
            "1 BHK",
            "2 BHK",
            "3 BHK",
            "4 BHK",
            "5 BHK"
        ]:

            rows = [
                r
                for r in observations
                if str(r.get("bhk") or "").strip().lower()
                == bhk.lower()
                and float(r.get("price") or 0) > 0
            ]

            # ----------------------------------------------------
            # No evidence for this BHK
            # ----------------------------------------------------
            if not rows:

                options.append(
                    AffordabilityOption(
                        category="residential",
                        label=bhk,
                        available=False,

                        property_status=property_status,

                        source_count=0,
                        observation_count=0,

                        confidence="low",

                        note=(
                            "No validated current price evidence was "
                            "extracted for this BHK in the requested location."
                        )
                    )
                )

                continue

            # ----------------------------------------------------
            # Remove duplicate observations
            # ----------------------------------------------------
            rows = _dedupe(rows)

            # ----------------------------------------------------
            # Separate usable area-based observations
            # from total-price-only observations.
            # ----------------------------------------------------
            area_rows = [
                r
                for r in rows
                if float(
                    r.get("canonical_price_per_sqft") or 0
                ) > 0
            ]

            price_only = [
                r
                for r in rows
                if not float(
                    r.get("canonical_price_per_sqft") or 0
                ) > 0
            ]

            # ----------------------------------------------------
            # Calculate validated ₹/sq.ft
            # ----------------------------------------------------
            ppsf = (
                robust_ppsf(area_rows)
                if area_rows
                else None
            )

            pricing_rows = area_rows or price_only

            prices = [
                float(r.get("price") or 0)
                for r in pricing_rows
                if float(r.get("price") or 0) > 0
            ]

            total = median(prices) if prices else None

            # ----------------------------------------------------
            # Calculate affordable area only when usable
            # ₹/sq.ft evidence exists.
            # ----------------------------------------------------
            area_sqft = (
                budget / ppsf
                if ppsf and ppsf > 0
                else None
            )

            # ----------------------------------------------------
            # Determine whether budget can cover typical price.
            # ----------------------------------------------------
            affordable = bool(
                total is not None
                and budget >= total
            )

            if affordable:
                note = (
                    "Budget appears sufficient for a typical current "
                    "listing in this BHK segment."
                )
            else:
                note = (
                    "Budget is below the typical current asking-price "
                    "evidence for this BHK segment."
                )

            # ----------------------------------------------------
            # Explain when only total-price evidence exists.
            # ----------------------------------------------------
            if price_only and not area_rows:
                note += (
                    " Some current listings expose total price and BHK "
                    "but not usable area, so affordability is based on "
                    "total asking-price evidence; price-per-sq-ft is "
                    "not fabricated."
                )

            # ----------------------------------------------------
            # Confidence
            # ----------------------------------------------------
            if len(rows) >= 5:
                confidence = "high"
            elif len(rows) >= 2:
                confidence = "medium"
            else:
                confidence = "low"

            source_count = len(
                set(
                    r.get("source_url")
                    for r in rows
                    if r.get("source_url")
                )
            )

            # ----------------------------------------------------
            # Add option
            # ----------------------------------------------------
            options.append(
                AffordabilityOption(
                    category="residential",
                    label=bhk,
                    available=affordable,

                    estimated_price=total,
                    estimated_price_per_sqft=ppsf,

                    estimated_area_sqft=area_sqft,

                    estimated_area_display=(
                        {"sq ft": area_sqft}
                        if area_sqft is not None
                        else {}
                    ),

                    property_status=property_status,

                    source_count=source_count,
                    observation_count=len(rows),

                    confidence=confidence,

                    note=note
                )
            )

        # --------------------------------------------------------
        # Residential response
        # --------------------------------------------------------
        resp = AffordabilityResponse(
            location=location,
            property_type=property_type,
            budget=budget,
            currency="INR",

            property_status=property_status,

            options=options,

            notes=(
                f"Budget affordability scenarios for "
                f"{property_type.replace('_', ' ')} at {location}. "
                "BHK is not an input; the system compares the same "
                "budget against current 1–5 BHK market evidence. "
                "Property status is used as a search constraint where "
                "source evidence supports it."
            ),

            sources=list(
                dict.fromkeys(all_sources)
            )[:20]
        )

        _log_affordability(
            current_user,
            req,
            resp
        )

        return resp

    # ============================================================
    # COMMERCIAL
    # ============================================================
    if property_type == "commercial":

        from app.services.source_service import search_and_extract

        raw, observations = await search_and_extract(
            location,
            "commercial",
            None,
            None
        )

        observations = _robust_filter(
            _dedupe(observations)
        )

        # --------------------------------------------------------
        # Commercial categories
        # --------------------------------------------------------
        categories = [
            ("Office", "office"),
            ("Shop", "shop"),
            ("Floor", "floor"),
            ("Warehouse", "warehouse")
        ]

        options = []

        for label, keyword in categories:

            # ----------------------------------------------------
            # Try category-specific evidence first.
            # ----------------------------------------------------
            rows = [
                r
                for r in observations
                if keyword in str(
                    r.get("evidence") or ""
                ).lower()
            ]

            # ----------------------------------------------------
            # If category-specific evidence is unavailable,
            # fall back to all commercial observations.
            # ----------------------------------------------------
            if not rows:
                rows = observations

            # ----------------------------------------------------
            # Calculate validated price per sq.ft.
            # ----------------------------------------------------
            ppsf = (
                robust_ppsf(rows)
                if rows
                else None
            )

            # ----------------------------------------------------
            # No usable evidence
            # ----------------------------------------------------
            if not ppsf or ppsf <= 0:

                options.append(
                    AffordabilityOption(
                        category="commercial",
                        label=label,
                        available=False,

                        confidence="low",

                        note=(
                            "No validated current evidence was found "
                            f"for the {label.lower()} category."
                        )
                    )
                )

                continue

            # ----------------------------------------------------
            # Budget / price-per-sq.ft
            # ----------------------------------------------------
            area_sqft = budget / ppsf

            # ----------------------------------------------------
            # Confidence
            # ----------------------------------------------------
            if len(rows) >= 5:
                confidence = "high"
            elif len(rows) >= 2:
                confidence = "medium"
            else:
                confidence = "low"

            source_count = len(
                set(
                    r.get("source_url")
                    for r in rows
                    if r.get("source_url")
                )
            )

            # ----------------------------------------------------
            # Commercial option
            # ----------------------------------------------------
            options.append(
                AffordabilityOption(
                    category="commercial",
                    label=label,
                    available=True,

                    estimated_price=budget,
                    estimated_price_per_sqft=ppsf,

                    estimated_area_sqft=area_sqft,

                    estimated_area_display={
                        "sq ft": area_sqft
                    },

                    source_count=source_count,
                    observation_count=len(rows),

                    confidence=confidence,

                    note=(
                        "Approximate commercial area purchasable at "
                        "the current validated comparable price; "
                        "exact configuration depends on the listing."
                    )
                )
            )

        # --------------------------------------------------------
        # Commercial response
        # --------------------------------------------------------
        resp = AffordabilityResponse(
            location=location,
            property_type="commercial",
            budget=budget,
            currency="INR",

            property_status=None,

            options=options,

            notes=(
                "Commercial affordability is shown by practical "
                "categories such as office, shop, floor and warehouse. "
                "Results are evidence-based estimates, not legal or "
                "lease approvals."
            ),

            sources=list(
                dict.fromkeys(
                    r.get("source_url")
                    for r in observations
                    if r.get("source_url")
                )
            )[:20]
        )

        _log_affordability(
            current_user,
            req,
            resp
        )

        return resp

    # ============================================================
    # UNSUPPORTED PROPERTY TYPE
    # ============================================================
    raise HTTPException(
        status_code=400,
        detail=(
            "Unsupported property type for affordability. "
            "Supported types: land, flat, villa, "
            "independent_house, commercial."
        )
    )



@app.post("/ingest-sources")
async def ingest_sources(req: SourceIngestRequest, current_user: CurrentUser = Depends(get_current_user)):
    observations,usable=await collect_from_urls(req.urls,req.property_type,req.bhk,req.location)
    coords=await geocode(req.location)
    for r in observations:
        r["location"]=req.location; r["property_type"]=req.property_type; r["bhk"]=req.bhk or r.get("bhk")
        if r.get("area") and r.get("area_unit"):
            try:r["area_sqft"]=to_sqft(float(r["area"]),r["area_unit"])
            except Exception:r["area_sqft"]=None
        if coords:r["latitude"]=coords.get("lat");r["longitude"]=coords.get("lon")
        r.setdefault("stored_at",datetime.now(timezone.utc).isoformat())
    safe_obs=_json_safe(observations)
    if safe_obs:
        users.add_search_history(current_user.user_id,{
            "type":"source_ingest",
            "request":_json_safe(req.model_dump()),
            "response":{"location":req.location,"inserted":len(safe_obs),"usable_sources":usable},
            "observations":safe_obs,
        })
    return _json_safe({"location":req.location,"inserted":len(safe_obs),"usable_sources":usable,"observations":observations})

@app.get("/sources/test")
async def source_test():
    return {"message":"Tavily Search discovers candidate pages; Tavily Extract retrieves selected page content; deterministic parsing creates validated observations. Social/discovery pages are ignored unless they expose structured price + area evidence."}

@app.get("/development-suitability")
async def development_suitability(area:float,unit:str="sq ft",location:str=""):
    sqft=to_sqft(area,unit)
    return {"location":location,"area_sqft":sqft,"disclaimer":"Planning heuristic only; local zoning, setbacks, FAR/FSI, road width and approvals must be checked with the relevant authority.","options":suitability(sqft,"land",location)}


# ============================================================
# Estimate Property
# ============================================================

@app.post("/estimate")
async def estimate_property(request: PropertyRequest):

    # --------------------------------------------------------
    # Start total execution timer
    # --------------------------------------------------------
    start_time = time.perf_counter()

    try:

        # ----------------------------------------------------
        # 1. Your existing property processing
        # ----------------------------------------------------

        location = request.location
        area = request.area
        area_unit = request.area_unit
        property_type = request.property_type

        # ----------------------------------------------------
        # 2. Tavily Search
        # ----------------------------------------------------
        tavily_start = time.perf_counter()

        # YOUR EXISTING TAVILY CODE HERE
        #
        # example:
        # search_result = tavily_client.search(...)
        #
        # Do not replace your existing Tavily logic.
        search_result = {}

        tavily_time = time.perf_counter() - tavily_start

        # ----------------------------------------------------
        # 3. Historical Price Processing
        # ----------------------------------------------------
        historical_start = time.perf_counter()

        # YOUR EXISTING HISTORICAL PRICE CODE HERE
        #
        # example:
        historical = []

        historical_time = time.perf_counter() - historical_start

        # ----------------------------------------------------
        # 4. Current Market Price Processing
        # ----------------------------------------------------
        market_start = time.perf_counter()

        # YOUR EXISTING MARKET PRICE CODE HERE
        #
        # example:
        typical_price_min = None
        typical_price_max = None

        market_time = time.perf_counter() - market_start

        # ----------------------------------------------------
        # 5. ML Prediction
        # ----------------------------------------------------
        ml_start = time.perf_counter()

        # YOUR EXISTING ML PREDICTION CODE HERE
        #
        # example:
        forecast = []

        ml_time = time.perf_counter() - ml_start

        # ----------------------------------------------------
        # 6. Database / History Save
        # ----------------------------------------------------
        database_start = time.perf_counter()

        # YOUR EXISTING MONGODB SAVE CODE HERE
        #
        # example:
        # await collection.insert_one(...)

        database_time = time.perf_counter() - database_start

        # ----------------------------------------------------
        # Calculate total execution time
        # ----------------------------------------------------
        total_time = time.perf_counter() - start_time

        # ----------------------------------------------------
        # Print performance information in terminal
        # ----------------------------------------------------
        print("\n==========================================")
        print("        LANDWISE PERFORMANCE")
        print("==========================================")
        print(f"Location          : {location}")
        print(f"Property Type     : {property_type}")
        print(f"Tavily Search     : {tavily_time:.2f} seconds")
        print(f"Historical Data   : {historical_time:.2f} seconds")
        print(f"Market Data       : {market_time:.2f} seconds")
        print(f"ML Prediction     : {ml_time:.2f} seconds")
        print(f"Database Save     : {database_time:.2f} seconds")
        print("------------------------------------------")
        print(f"TOTAL TIME        : {total_time:.2f} seconds")
        print("==========================================\n")

        # ----------------------------------------------------
        # Final API Response
        # ----------------------------------------------------
        return {
            "location": location,
            "area": area,
            "area_unit": area_unit,
            "property_type": property_type,

            # Existing response data
            "historical": historical,
            "forecast": forecast,
            "typical_price_min": typical_price_min,
            "typical_price_max": typical_price_max,

            # Performance information
            "performance": {
                "tavily_seconds": round(tavily_time, 2),
                "historical_seconds": round(historical_time, 2),
                "market_seconds": round(market_time, 2),
                "ml_seconds": round(ml_time, 2),
                "database_seconds": round(database_time, 2),
                "total_seconds": round(total_time, 2),
            },

            # Simple value for frontend
            "processing_time_seconds": round(total_time, 2),
        }

    except Exception as e:

        # ----------------------------------------------------
        # Calculate time even when an error occurs
        # ----------------------------------------------------
        total_time = time.perf_counter() - start_time

        print(
            f"LandWise request failed after "
            f"{total_time:.2f} seconds"
        )

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


# Safe cache/Tavily debug logging. These values are only available inside
# the request handler scope; guard access so module import does not crash.
print(
    f"[CACHE] Lookup location: "
    f"{globals().get('location', 'unknown')}"
)

# Immediately after your existing cache lookup:
print(
    "[CACHE] Status: "
    + (
        "HIT"
        if globals().get("cached_record") is not None
        else "MISS"
    )
)

# Immediately before the Tavily API call:
print("[TAVILY] Starting external search")