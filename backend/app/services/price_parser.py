import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Optional

from app.unit_utils import normalize_unit, to_sqft


@dataclass
class ParsedObservation:
    source_url: str
    source_domain: str
    source_type: str
    source_quality: float
    price: float
    currency: str
    area: Optional[float]
    area_unit: Optional[str]
    price_per_unit: Optional[float]
    canonical_price_per_sqft: Optional[float]
    property_type: str
    bhk: Optional[str]
    evidence: str
    retrieved_at: str


DOMAIN_QUALITY = {
    "housing.com": ("property_portal", 0.85),
    "99acres.com": ("property_portal", 0.85),
    "1acre.in": ("property_portal", 0.80),
    "baanknet.com": ("auction_portal", 0.82),
    "olx.in": ("classifieds", 0.55),
    "assetlyhq.com": ("guidance_value", 0.35),
    "instagram.com": ("social", 0.25),
    "youtube.com": ("video", 0.35),
    "youtu.be": ("video", 0.35),
}

# Keep the number group mandatory and bounded. The old parser could encounter
# malformed/empty numeric groups in scraped text and crash the entire request.
PRICE_RE = re.compile(
    r"(?<![\w.])"
    r"(?P<currency>₹|rs\.?|inr|usd|\$|eur|€|gbp|£)?"
    r"\s*"
    r"(?P<num>\d[\d,]*(?:\.\d+)?)"
    r"\s*"
    r"(?P<scale>crore|crores|cr|lakh|lakhs|lac|lacs|million|m|k)?"
    r"(?![\w.])",
    re.I,
)

AREA_RE = re.compile(
    r"(?<![\w.])"
    r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>sq\.?\s*(?:ft|feet|yd|yard|yards|m|meter|meters|metre|metres)|"
    r"acre|acres|cent|cents|gunta|guntas|marla|marlas|hectare|hectares|"
    r"bigha|bighas)"
    r"(?![\w.])",
    re.I,
)

PER_RE = re.compile(
    r"(?:per|/|each)\s*"
    r"(?P<unit>sq\.?\s*(?:ft|feet|yd|yard|yards|m|meter|meters|metre|metres)|"
    r"acre|acres|cent|cents|gunta|guntas|marla|marlas|hectare|hectares|"
    r"bigha|bighas)",
    re.I,
)


def source_meta(url: str):
    domain = urlparse(url).netloc.lower().removeprefix("www.")
    return DOMAIN_QUALITY.get(domain, ("website", 0.45))


def _number(s: str | None) -> Optional[float]:
    """Safely parse a scraped numeric value.

    Scraped HTML/social text is untrusted. Never let a malformed or empty
    regex capture terminate the FastAPI request.
    """
    if s is None:
        return None
    value = str(s).strip().replace(",", "")
    if not value:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _price_value(num: float | None, scale: str | None) -> Optional[float]:
    if num is None or num <= 0:
        return None
    s = (scale or "").lower()
    if s in {"crore", "crores", "cr"}:
        return num * 10_000_000
    if s in {"lakh", "lakhs", "lac", "lacs"}:
        return num * 100_000
    if s in {"million", "m"}:
        return num * 1_000_000
    if s == "k":
        return num * 1_000
    return num


def _currency(token: str | None) -> str:
    t = (token or "").lower()
    if "usd" in t or "$" in t:
        return "USD"
    if "eur" in t or "€" in t:
        return "EUR"
    if "gbp" in t or "£" in t:
        return "GBP"
    return "INR"


def _area_unit(raw: str) -> str:
    s = raw.lower().replace(".", "").strip()
    if "sq" in s and ("yd" in s or "yard" in s):
        return "sq yd"
    if "sq" in s and ("m" in s or "meter" in s or "metre" in s):
        return "sq m"
    if "sq" in s and ("ft" in s or "feet" in s):
        return "sq ft"
    if "acre" in s:
        return "acre"
    if "cent" in s:
        return "cent"
    if "gunta" in s:
        return "gunta"
    if "marla" in s:
        return "marla"
    if "hectare" in s:
        return "hectare"
    if "bigha" in s:
        return "bigha"
    return normalize_unit(s)


def infer_bhk(text: str) -> Optional[str]:
    m = re.search(r"\b([1-5])\s*\+?\s*BHK\b", text, re.I)
    if m:
        return f"{m.group(1)} BHK"
    m = re.search(r"\b(5\+|6)\s*BHK\b", text, re.I)
    if m:
        return "5+ BHK"
    return None

def infer_property_type(text: str, requested: str) -> str:
    t = text.lower()
    if requested != "land":
        return requested
    if any(x in t for x in ["flat", "apartment", "bhk"]):
        return "flat"
    if "villa" in t:
        return "villa"
    if "independent house" in t:
        return "independent_house"
    if any(x in t for x in ["shop", "office", "warehouse", "commercial"]):
        return "commercial"
    return "land"


PRICE_CUE_RE = re.compile(r"\b(?:price|rate|cost|asking|sale|selling|worth|value|plot|land)\b|(?:₹|rs\.?|inr|\$|usd|€|eur|£|gbp)", re.I)


def _is_price_candidate(match: re.Match, text: str) -> bool:
    gd = match.groupdict()
    # Currency or scale is the strongest signal.
    if gd.get("currency") or gd.get("scale"):
        return True
    # Bare numbers are accepted only when an explicit price/rate word is very
    # close. This prevents years, phone numbers, counts and page statistics
    # from becoming prices.
    lo=max(0,match.start()-12); hi=min(len(text),match.end()+12)
    near=text[lo:hi]
    if re.search(r"\b(?:price|rate|cost|asking|sale|selling|worth|value)\b",near,re.I):
        return True
    # A bare value immediately followed by a unit phrase is a valid compact
    # form such as `950 per sq yard`.
    after=text[match.end():min(len(text),match.end()+12)]
    return bool(re.match(r"\s*(?:per|/)\s*sq\.?\s*(?:ft|feet|yd|yard|yards|m|meter|meters|metre|metres)",after,re.I))


def extract_observations(
    url: str,
    title: str,
    content: str,
    requested_property_type: str = "land",
    bhk: str | None = None,
) -> list[ParsedObservation]:
    text = " ".join((title or "", content or "")).strip()
    if not text:
        return []

    domain_type, quality = source_meta(url)
    now = datetime.now(timezone.utc).isoformat()
    observations: list[ParsedObservation] = []
    areas = list(AREA_RE.finditer(text))
    prices = [m for m in PRICE_RE.finditer(text) if _is_price_candidate(m, text)]

    def add_observation(pm, area_m=None, explicit_unit=None):
        num = _number(pm.groupdict().get("num"))
        price = _price_value(num, pm.groupdict().get("scale"))
        if price is None:
            return
        currency = _currency(pm.groupdict().get("currency"))
        if currency != "INR":
            return  # current model is INR-only; never mix currencies
        if explicit_unit is None and (price < 10_000 or price > 1_000_000_000):
            return
        if price > 1_000_000_000:
            return

        area = None
        unit = explicit_unit
        ppu = None
        ppsf = None
        if area_m is not None:
            area = _number(area_m.groupdict().get("num"))
            if area is None or area <= 0:
                return
            unit = unit or _area_unit(area_m.group("unit"))
            try:
                sqft = to_sqft(area, unit)
                if sqft <= 0:
                    return
                ppu = price / area
                ppsf = price / sqft
            except (TypeError, ValueError, ZeroDivisionError):
                return
        elif explicit_unit:
            try:
                sqft_for_one = to_sqft(1, explicit_unit)
                if sqft_for_one <= 0:
                    return
                ppu = price
                ppsf = price / sqft_for_one
            except (TypeError, ValueError, ZeroDivisionError):
                return
        else:
            return

        lo = max(0, min(pm.start(), area_m.start() if area_m else pm.start()) - 90)
        hi = min(len(text), max(pm.end(), area_m.end() if area_m else pm.end()) + 120)
        window = text[lo:hi]
        ptype = infer_property_type(window, requested_property_type)
        detected_bhk = bhk or infer_bhk(window)
        if requested_property_type in {"flat", "villa", "independent_house"}:
            bhk_matches = re.findall(r"\b(?:1|2|3|4|5)\s*\+?\s*BHK\b", window, re.I)
            if len({m.replace(" ", "").lower() for m in bhk_matches}) > 1:
                return
        observations.append(ParsedObservation(
            source_url=url,
            source_domain=urlparse(url).netloc.lower().removeprefix("www."),
            source_type=domain_type,
            source_quality=quality,
            price=price,
            currency=currency,
            area=area,
            area_unit=unit,
            price_per_unit=ppu,
            canonical_price_per_sqft=ppsf,
            property_type=ptype,
            bhk=detected_bhk,
            evidence=window[:700],
            retrieved_at=now,
        ))

    # 1. Explicit statements such as "₹950 per sq yard".
    for pm in prices:
        lo, hi = max(0, pm.start() - 20), min(len(text), pm.end() + 90)
        window = text[lo:hi]
        per = PER_RE.search(window)
        if per:
            add_observation(pm, explicit_unit=_area_unit(per.group("unit")))

    # 2. Listing totals such as "₹15 lakh for 166 sq yd".
    # Pair only if price and area are close and the price is explicitly a price.
    for am in areas[:80]:
        candidates = [pm for pm in prices if abs(pm.start() - am.end()) <= 180]
        if not candidates:
            continue
        # Prefer the closest price, but don't reuse an area with a distant price.
        pm = min(candidates, key=lambda x: abs(x.start() - am.end()))
        # Avoid interpreting an explicit per-unit price as a total listing price.
        lo, hi = max(0, pm.start() - 10), min(len(text), pm.end() + 90)
        if PER_RE.search(text[lo:hi]):
            continue
        add_observation(pm, area_m=am)

    # 3. Deduplicate repeated snippets from a single page.
    unique = {}
    for o in observations:
        ppsf = round(o.canonical_price_per_sqft or 0, 6)
        key = (o.source_url, round(o.price, 2), round(o.area or 0, 4), o.area_unit, ppsf)
        unique[key] = o
    return list(unique.values())[:40]

def to_dict(o: ParsedObservation) -> dict:
    return asdict(o)


def extract_residential_price_only(url: str, title: str, content: str, requested_property_type: str, expected_bhk: str) -> list[dict]:
    """Extract explicit total asking prices for a residential BHK scenario when
    a listing exposes price + BHK but does not expose usable area. This is used
    only by affordability; the core Price tab still requires price + area.
    """
    text = " ".join((title or "", content or "")).strip()
    if not text or not expected_bhk:
        return []
    target = expected_bhk.lower().replace(" ", "")
    domain_type, quality = source_meta(url)
    now = datetime.now(timezone.utc).isoformat()
    out = []
    for bm in re.finditer(r"\b(?:1|2|3|4|5)\s*BHK\b", text, re.I):
        if bm.group(0).lower().replace(" ", "") != target:
            continue
        lo = max(0, bm.start()-120); hi = min(len(text), bm.end()+180)
        window = text[lo:hi]
        window_bhks = {
            m.group(0).lower().replace(" ", "")
            for m in re.finditer(r"\b(?:1|2|3|4|5)\s*BHK\b", window, re.I)
        }
        if window_bhks - {target}:
            continue
        for pm in PRICE_RE.finditer(window):
            if not _is_price_candidate(pm, window):
                continue
            # Do not accept a price-per-unit statement as a total price.
            p_lo=max(0,pm.start()-10); p_hi=min(len(window),pm.end()+80)
            if PER_RE.search(window[p_lo:p_hi]):
                continue
            price=_price_value(_number(pm.groupdict().get("num")),pm.groupdict().get("scale"))
            if price is None or price < 100000 or price > 1000000000:
                continue
            if _currency(pm.groupdict().get("currency")) != "INR":
                continue
            out.append({
                "source_url": url, "source_domain": urlparse(url).netloc.lower().removeprefix("www."),
                "source_type": domain_type, "source_quality": quality, "price": price, "currency": "INR",
                "area": None, "area_unit": None, "price_per_unit": None, "canonical_price_per_sqft": None,
                "property_type": requested_property_type, "bhk": expected_bhk,
                "evidence": window[:700], "retrieved_at": now, "price_only": True
            })
            break
    unique={}
    for r in out: unique[(r["source_url"],round(r["price"],2),r["bhk"])] = r
    return list(unique.values())[:10]
