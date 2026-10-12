from __future__ import annotations

import re
from typing import Any

import numpy as np
from urllib.parse import urlparse

from app.services.source_service import tavily_search, tavily_extract, SourceServiceError
from app.unit_utils import convert_price_per_unit

# Current market sources are deliberately separated from government guidance
# sources. Guidance/circle rates are registration floors, not typical sale prices.
MARKET_DOMAINS = [
    "magicbricks.com", "99acres.com", "housing.com", "nobroker.in",
    "squareyards.com", "commonfloor.com", "1acre.in", "proptiger.com",
    "housing.com", "realtymyths.com", "propyards.com",
]
GUIDANCE_DOMAINS = [
    "registration.telangana.gov.in", "assetlyhq.com", "tg.verified.realestate",
    "landrate.in",
]

UNIT_PATTERN = r"(?:sq[\s.\-]*(?:ft|feet|foot)|sq[\s.\-]*(?:yd|yrd|yard|yards)|sqft|sqyd)"
PRICE_UNIT_RE = re.compile(
    rf"(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)\s*(?:/|per)\s*({UNIT_PATTERN})\b",
    re.I,
)
REVERSE_PRICE_UNIT_RE = re.compile(
    rf"([\d,]+(?:\.\d+)?)\s*({UNIT_PATTERN})\s*(?:/|per)\s*(?:₹|rs\.?|inr)?",
    re.I,
)
RANGE_RE = re.compile(
    rf"(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)\s*(?:/|per)\s*({UNIT_PATTERN})\b",
    re.I,
)


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _canonical_unit(raw: str) -> str:
    s = raw.lower().replace(".", "").strip()
    if "yd" in s or "yrd" in s or "yard" in s:
        return "sq yd"
    return "sq ft"


def _num(value: str) -> float | None:
    try:
        n = float(value.replace(",", "").strip())
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _collect_values(text: str) -> list[tuple[float, str, str]]:
    """Return (value, unit, kind) where kind is range or average."""
    text = re.sub(r"\s+", " ", text or "")
    values: list[tuple[float, str, str]] = []
    consumed: set[tuple[int, int]] = set()

    # Prefer explicit ranges. Each endpoint is retained so a multi-source
    # market range is not accidentally collapsed to a single point.
    for m in RANGE_RE.finditer(text):
        lo, hi = _num(m.group(1)), _num(m.group(2))
        if lo is None or hi is None:
            continue
        unit = _canonical_unit(m.group(3))
        if hi < lo:
            lo, hi = hi, lo
        # Reject obviously non-price values and implausible unit prices.
        if lo < 50 or hi > 100_000_000:
            continue
        values.extend([(lo, unit, "range"), (hi, unit, "range")])
        consumed.add((m.start(), m.end()))

    for regex in (PRICE_UNIT_RE, REVERSE_PRICE_UNIT_RE):
        for m in regex.finditer(text):
            if any(a <= m.start() and m.end() <= b for a, b in consumed):
                continue
            n = _num(m.group(1))
            if n is None or n < 50 or n > 100_000_000:
                continue
            values.append((n, _canonical_unit(m.group(2)), "average"))
    return values


def _collect_response_text(response: dict[str, Any]) -> tuple[str, list[str]]:
    chunks: list[str] = []
    urls: list[str] = []
    answer = response.get("answer")
    if isinstance(answer, str):
        chunks.append(answer)
    for item in response.get("results") or []:
        if not isinstance(item, dict):
            continue
        for key in ("title", "content", "snippet"):
            if isinstance(item.get(key), str):
                chunks.append(item[key])
        if item.get("url"):
            urls.append(str(item["url"]))
    return "\n".join(chunks), list(dict.fromkeys(urls))


async def current_market_range(location: str) -> dict[str, Any]:
    """Fetch a location-specific *current market* range using live Tavily results.

    Market portals are primary. Government guidance sources are only a fallback
    and are explicitly marked as guidance so the UI never mistakes registration
    floors for typical negotiated market prices.
    """
    query = (
        f"current 2026 residential plot land sale price {location} "
        f"locality price range average per sq ft per sq yard recent listings"
    )
    response = await tavily_search(
        query,
        max_results=8,
        include_domains=MARKET_DOMAINS,
        search_depth="advanced",
        include_answer=True,
    )
    text, urls = _collect_response_text(response)
    market_values: list[tuple[float, str, str, str]] = []

    for item in response.get("results") or []:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        url = str(item["url"])
        domain = _domain(url)
        if not any(domain == d or domain.endswith("." + d) for d in MARKET_DOMAINS):
            continue
        item_text = " ".join(str(item.get(k) or "") for k in ("title", "content", "snippet"))
        for value, unit, kind in _collect_values(item_text):
            market_values.append((value, unit, kind, url))

    # Extract the strongest current market pages when snippets are too sparse.
    if len(market_values) < 2 and urls:
        try:
            extracted = await tavily_extract(urls[:5], max_urls=5)
            for item in extracted.get("results") or []:
                url = str(item.get("url") or "")
                raw = str(item.get("raw_content") or item.get("content") or "")
                if not raw:
                    continue
                for value, unit, kind in _collect_values(raw):
                    market_values.append((value, unit, kind, url))
        except Exception:
            pass

    if market_values:
        # Normalize everything to sq ft before calculating the range. Use only
        # current market portal evidence; never mix government floors here.
        normalized = []
        for value, unit, kind, url in market_values:
            normalized.append((convert_price_per_unit(value, unit, "sq ft"), kind, url))
        # Prefer explicit published ranges. If several portals contribute
        # values, use the observed extrema, but cap the influence of a single
        # obvious outlier with a percentile envelope when enough observations
        # exist. This keeps a city-wide portal outlier from becoming the
        # dashboard's "typical" locality range.
        vals = sorted(v for v, _, _ in normalized)
        if len(vals) >= 8:
            lo = float(np.percentile(vals, 10))
            hi = float(np.percentile(vals, 90))
        else:
            lo, hi = min(vals), max(vals)
        return {
            "status": "market",
            "min_price_per_sqft": round(lo, 2),
            "max_price_per_sqft": round(hi, 2),
            "sources": list(dict.fromkeys(u for _, _, u in normalized if u))[:12],
            "source_count": len(set(u for _, _, u in normalized if u)),
            "query": query,
            "evidence": text[:12000],
        }

    # Fallback: current Telangana guidance values. This is better than inventing
    # a market quote, but it is explicitly identified as a government floor.
    guidance_query = (
        f"{location} Telangana 2026 current land plot market value guidance value "
        f"range per square yard"
    )
    guidance = await tavily_search(
        guidance_query,
        max_results=6,
        include_domains=GUIDANCE_DOMAINS,
        search_depth="advanced",
        include_answer=True,
    )
    gtext, gurls = _collect_response_text(guidance)
    guidance_values: list[tuple[float, str, str]] = []
    for item in guidance.get("results") or []:
        url = str(item.get("url") or "")
        if not url:
            continue
        item_text = " ".join(str(item.get(k) or "") for k in ("title", "content", "snippet"))
        for value, unit, kind in _collect_values(item_text):
            guidance_values.append((value, unit, url))
    if guidance_values:
        normalized = [convert_price_per_unit(v, u, "sq ft") for v, u, _ in guidance_values]
        return {
            "status": "guidance_fallback",
            "min_price_per_sqft": round(min(normalized), 2),
            "max_price_per_sqft": round(max(normalized), 2),
            "sources": list(dict.fromkeys(u for _, _, u in guidance_values))[:12],
            "source_count": len(set(u for _, _, u in guidance_values)),
            "query": guidance_query,
            "evidence": gtext[:12000],
        }

    return {
        "status": "unavailable",
        "min_price_per_sqft": None,
        "max_price_per_sqft": None,
        "sources": [],
        "source_count": 0,
        "query": query,
        "evidence": text[:12000],
    }
