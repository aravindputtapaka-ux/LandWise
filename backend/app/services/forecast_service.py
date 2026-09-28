from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Any

import numpy as np
from sklearn.linear_model import LinearRegression, Ridge

from app.unit_utils import to_sqft
from app.services.price_parser import extract_observations


@dataclass
class HistoricalPoint:
    year: int
    price_per_sqft: float
    location: str
    source_domain: str = ""
    source_url: str = ""
    price_type: str = "unknown"
    evidence: str = ""


PRICE_RE = re.compile(
    r"(?:₹|rs\.?|inr)\s*([0-9][0-9,]*(?:\.\d+)?)\s*(crore|cr|lakh|lac|lacs|lakhs|k)?",
    re.I,
)
YEAR_RE = re.compile(r"\b(20(?:2[0-9]))\b")
PER_UNIT_RE = re.compile(
    r"(?:per|/|\b)\s*(sq\.?\s*(?:ft|feet|yd|yard|yards|m|meter|meters|metre|metres)|acre|acres|cent|cents|gunta|guntas|marla|marlas|hectare|hectares|bigha|bighas)\b",
    re.I,
)
NUMBER_RE = re.compile(r"(?<!\w)([0-9][0-9,]*(?:\.\d+)?)(?!\w)")


def _money(value: str, scale: str | None = None) -> float:
    n = float(value.replace(",", ""))
    s = (scale or "").lower()
    if s in {"crore", "cr"}:
        return n * 10_000_000
    if s in {"lakh", "lac", "lacs", "lakhs"}:
        return n * 100_000
    if s == "k":
        return n * 1_000
    return n


def _unit(raw: str) -> str:
    s = raw.lower().replace(".", "").strip()
    if "sq" in s and ("yd" in s or "yard" in s): return "sq yd"
    if "sq" in s and ("ft" in s or "feet" in s): return "sq ft"
    if "sq" in s and ("m" in s or "meter" in s or "metre" in s): return "sq m"
    if "acre" in s: return "acre"
    if "cent" in s: return "cent"
    if "gunta" in s: return "gunta"
    if "marla" in s: return "marla"
    if "hectare" in s: return "hectare"
    if "bigha" in s: return "bigha"
    return "sq ft"


def _price_per_sqft_from_fragment(fragment: str) -> float | None:
    # Explicit "₹950 per sq yard" / "₹950/sq yd".
    for pm in PRICE_RE.finditer(fragment):
        tail = fragment[pm.end():pm.end() + 45]
        um = PER_UNIT_RE.search(tail)
        if um:
            price = _money(pm.group(1), pm.group(2))
            unit = _unit(um.group(1))
            try:
                return price / to_sqft(1, unit)
            except Exception:
                return None

    # Common table form: 950 / sq yd, 40 / sq ft, etc., without currency.
    um = PER_UNIT_RE.search(fragment)
    if um:
        before = fragment[max(0, um.start() - 80):um.start()]
        nums = list(NUMBER_RE.finditer(before))
        if nums:
            n = float(nums[-1].group(1).replace(",", ""))
            if 1 <= n <= 10_000_000:
                unit = _unit(um.group(1))
                try:
                    return n / to_sqft(1, unit)
                except Exception:
                    return None

    # Table headings may already say "Price/sq ft"; accept a nearby numeric value.
    lower = fragment.lower()
    if any(x in lower for x in ["price per sq ft", "price/sq ft", "₹/sq ft", "inr/sq ft", "per sqft"]):
        nums = list(NUMBER_RE.finditer(fragment))
        for nm in reversed(nums):
            n = float(nm.group(1).replace(",", ""))
            if 1 <= n <= 10_000_000:
                return n
    return None


def _cell_number(cell: str) -> float | None:
    m = PRICE_RE.search(cell or "")
    if m:
        return _money(m.group(1), m.group(2))
    m = re.search(r"(?<!\w)([0-9][0-9,]*(?:\.\d+)?)(?!\w)", cell or "")
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _header_index(headers: list[str], patterns: list[str]) -> int | None:
    for i, h in enumerate(headers):
        lh = re.sub(r"[^a-z0-9]+", " ", h.lower()).strip()
        if any(re.search(p, lh) for p in patterns):
            return i
    return None


def parse_historical_text(text: str, location: str, source_domain: str = "", source_url: str = "") -> list[HistoricalPoint]:
    """Conservative parser for year-specific historical price evidence.

    The old parser looked at *any* number in a row and selected the last one.
    That can turn a table such as ``2022 | 650 | 900 | ...`` into the same
    900 value for every year.  This version reads the declared price column,
    or calculates price/sqft only from the original-price and original-area
    columns in the same row. It never borrows a number from another row.
    """
    if not text:
        return []
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    points: list[HistoricalPoint] = []
    lines = text.splitlines()

    # ---------- Structured markdown tables ----------
    for i, line in enumerate(lines[:-1]):
        if "|" not in line or "year" not in line.lower():
            continue
        headers = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(headers) < 2:
            continue
        # Find the separator row and parse subsequent rows until the table ends.
        j = i + 1
        if j < len(lines) and re.fullmatch(r"\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*", lines[j]):
            j += 1
        year_idx = _header_index(headers, [r"^year$", r"year"])
        ppsf_idx = _header_index(headers, [r"price.*sq.*ft", r"sq.*ft.*price", r"inr.*sq.*ft"])
        original_price_idx = _header_index(headers, [r"original.*price", r"total.*price", r"price"])
        original_area_idx = _header_index(headers, [r"original.*area", r"area"])
        if year_idx is None:
            continue
        while j < len(lines) and "|" in lines[j]:
            cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
            if len(cells) < len(headers):
                j += 1
                continue
            ym = YEAR_RE.fullmatch(cells[year_idx].strip()) or YEAR_RE.search(cells[year_idx])
            if not ym:
                j += 1
                continue
            year = int(ym.group(1))
            ppsf = None
            if ppsf_idx is not None and ppsf_idx < len(cells):
                raw = cells[ppsf_idx]
                ppsf = _price_per_sqft_from_fragment(raw)
                if ppsf is None:
                    n = _cell_number(raw)
                    if n is not None and 0 < n < 10_000_000:
                        ppsf = n
            # Only calculate from values in this exact row.
            if ppsf is None and original_price_idx is not None and original_area_idx is not None:
                price = _cell_number(cells[original_price_idx])
                area = _cell_number(cells[original_area_idx])
                if price and area and area > 0:
                    area_text = cells[original_area_idx].lower()
                    unit = "sq ft"
                    if "acre" in area_text: unit = "acre"
                    elif "sq yd" in area_text or "yard" in area_text: unit = "sq yd"
                    elif "sq m" in area_text or "sqm" in area_text: unit = "sq m"
                    elif "cent" in area_text: unit = "cent"
                    elif "gunta" in area_text: unit = "gunta"
                    ppsf = price / to_sqft(area, unit)
            if ppsf is not None and 0 < ppsf < 10_000_000:
                row = " | ".join(cells)
                ptype = "asking" if re.search(r"asking|listing", row, re.I) else ("auction" if re.search(r"auction", row, re.I) else "unknown")
                points.append(HistoricalPoint(year, float(ppsf), location, source_domain, source_url, ptype, row[:700]))
            j += 1

    # ---------- Prose / non-table evidence ----------
    # Do NOT run this fallback against a response that contains a historical
    # table. It can otherwise attach a nearby/current value to every year.
    has_historical_table = any("|" in ln and "year" in ln.lower() for ln in lines[:80])
    if not has_historical_table:
        for ym in YEAR_RE.finditer(text):
            year = int(ym.group(1))
            frag = text[max(0, ym.start() - 100):min(len(text), ym.end() + 180)]
            ppsf = _price_per_sqft_from_fragment(frag)
            if ppsf is not None and 0 < ppsf < 10_000_000:
                ptype = "asking" if re.search(r"asking|listing", frag, re.I) else ("auction" if re.search(r"auction", frag, re.I) else "unknown")
                points.append(HistoricalPoint(year, float(ppsf), location, source_domain, source_url, ptype, frag[:700]))

    # Deduplicate exact evidence only. Do not collapse different sources before
    # the caller can assess independent evidence.
    unique = {}
    for p in points:
        key = (p.year, round(p.price_per_sqft, 4), p.source_domain, p.source_url, p.evidence)
        unique[key] = p
    return sorted(unique.values(), key=lambda x: (x.year, x.source_domain, x.source_url))

def extract_year_price_pairs(
    text: str,
    location: str,
    source_domain: str = "",
    source_url: str = "",
) -> list[HistoricalPoint]:
    """
    Extract explicit YEAR -> PRICE/SQFT relationships from Tavily
    snippets/raw page text.

    This is intentionally conservative:
    - A year and price must occur close together.
    - The price must have an explicit land-price unit.
    - No missing years are invented.
    - Current/undated prices are ignored.
    """

    if not text:
        return []

    text = (
        text.replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u00a0", " ")
    )

    results = []

    # Examples handled:
    # 2022: ₹500 per sq ft
    # 2023 - Rs 650/sq ft
    # 2024 land price was ₹750 per square feet
    # 2025 | ₹900 | per sq ft
    pattern = re.compile(
        r"""
        (?P<year>20(?:2[0-9]))
        \s*
        (?:
            :
            |
            -
            |
            \|
            |
            was
            |
            land\s+(?:price|rate)\s+(?:was|of)?
        )
        \s*
        (?:Rs\.?|INR|₹)?
        \s*
        (?P<price>[0-9][0-9,\s]*(?:\.\d+)?)
        \s*
        (?P<scale>crore|cr|lakh|lac|lakhs|k)?
        \s*
        (?:per|/|at)
        \s*
        (?P<unit>
            sq\.?\s*ft
            |
            sqft
            |
            square\s+feet
            |
            sq\.?\s*yd
            |
            sq\.?\s*yard
            |
            square\s+yard
            |
            sq\.?\s*m
            |
            square\s+met(?:er|re)s?
            |
            acre
            |
            acres
        )
        """,
        re.I | re.X,
    )

    for m in pattern.finditer(text):
        try:
            year = int(m.group("year"))

            price = _money(
                m.group("price").replace(" ", ""),
                m.group("scale"),
            )

            unit = _unit(m.group("unit"))

            price_per_sqft = price / to_sqft(1, unit)

            if (
                not math.isfinite(price_per_sqft)
                or price_per_sqft <= 0
                or price_per_sqft > 10_000_000
            ):
                continue

            fragment = text[
                max(0, m.start() - 120):
                min(len(text), m.end() + 180)
            ]

            # Reject obvious non-property contexts.
            if re.search(
                r"\b(flat|apartment|rent|rental|salary|gold|car|bike)\b",
                fragment,
                re.I,
            ):
                continue

            results.append(
                HistoricalPoint(
                    year=year,
                    price_per_sqft=float(price_per_sqft),
                    location=location,
                    source_domain=source_domain,
                    source_url=source_url,
                    price_type=(
                        "auction"
                        if re.search(r"\bauction\b", fragment, re.I)
                        else "asking"
                        if re.search(
                            r"\b(asking|listing)\b",
                            fragment,
                            re.I,
                        )
                        else "unknown"
                    ),
                    evidence=fragment[:700],
                )
            )

        except Exception:
            continue

    # Fallback for common historical prose/listing text such as:
    # "2024: ₹20 lakh for 2,400 sq ft". The earlier regex only accepted
    # explicit "price per sq ft" wording, which caused valid historical
    # rows to disappear even though price + area were present.
    for ym in YEAR_RE.finditer(text):
        year = int(ym.group(1))
        fragment = text[max(0, ym.start() - 120): min(len(text), ym.end() + 520)]
        try:
            parsed = extract_observations(
                source_url or "https://historical.local/",
                "",
                fragment,
                "land",
                None,
            )
        except Exception:
            parsed = []
        for obs in parsed:
            ppsf = obs.canonical_price_per_sqft
            if ppsf is None or not math.isfinite(float(ppsf)) or not (0 < float(ppsf) < 10_000_000):
                continue
            results.append(
                HistoricalPoint(
                    year=year,
                    price_per_sqft=float(ppsf),
                    location=location,
                    source_domain=source_domain,
                    source_url=source_url,
                    price_type=("auction" if "auction" in fragment.lower() else "asking" if re.search(r"\b(asking|listing)\b", fragment, re.I) else "unknown"),
                    evidence=fragment[:700],
                )
            )

    # Remove exact duplicates
    unique = {}

    for p in results:
        key = (
            p.year,
            round(p.price_per_sqft, 4),
            p.source_domain,
            p.source_url,
        )
        unique[key] = p

    return sorted(
        unique.values(),
        key=lambda x: (
            x.year,
            x.source_domain,
        ),
    )
def forecast(points: list[HistoricalPoint], horizon: int = 3) -> dict[str, Any]:
    """Small-data land-price forecast.

    With 4 years, a log-linear trend is deliberately used instead of a high-
    capacity model. As more historical years/observations are collected, Ridge
    can use the richer feature set without changing the response contract.
    """
    # Aggregate multiple independent observations for the same year instead
    # of silently taking whichever source happened to appear last. Median is
    # resistant to one unusually high/low listing.
    by_year: dict[int, list[HistoricalPoint]] = {}
    for p in points:
        if p.price_per_sqft > 0 and math.isfinite(p.price_per_sqft):
            by_year.setdefault(int(p.year), []).append(p)

    clean: list[HistoricalPoint] = []
    for year in sorted(by_year):
        bucket = by_year[year]
        value = float(median([p.price_per_sqft for p in bucket]))
        sources = sorted({p.source_domain for p in bucket if p.source_domain})
        clean.append(HistoricalPoint(
            year=year,
            price_per_sqft=value,
            location=bucket[0].location,
            source_domain=", ".join(sources),
            source_url="; ".join(sorted({p.source_url for p in bucket if p.source_url})[:5]),
            price_type="aggregated",
            evidence=f"Median of {len(bucket)} validated historical observation(s) for {year}."
        ))

    if len(clean) < 3:
        return {
            "status": "insufficient_historical_data",
            "historical_years": [p.year for p in clean],
            "historical_points": [p.__dict__ for p in clean],
            "forecast": [],
            "growth_rates": [],
            "model": "not_trained",
            "reason": "At least 3 validated historical years are required.",
        }

    years = np.asarray([p.year for p in clean], dtype=float)
    prices = np.asarray([p.price_per_sqft for p in clean], dtype=float)
    # Log transform makes multiplicative market growth more natural and keeps
    # forecasts positive.
    model = LinearRegression()
    model.fit(years.reshape(-1, 1), np.log(prices))
    fitted = np.exp(model.predict(years.reshape(-1, 1)))
    residual = float(np.sqrt(np.mean((np.log(prices) - np.log(fitted)) ** 2)))

    last_year = int(years[-1])
    future_years = np.arange(last_year + 1, last_year + horizon + 1, dtype=float)
    future_prices = np.exp(model.predict(future_years.reshape(-1, 1)))
    forecasts = []
    for y, v in zip(future_years.astype(int), future_prices):
        forecasts.append({"year": int(y), "predicted_price_per_sqft": round(float(v), 2)})

    growth_rates = []
    for a, b in zip(prices[:-1], prices[1:]):
        growth_rates.append(round(float((b / a - 1) * 100), 2))
    forecast_growth = []
    prev = prices[-1]
    for v in future_prices:
        forecast_growth.append(round(float((v / prev - 1) * 100), 2))
        prev = v

    direction = "increasing" if model.coef_[0] > 0 else "decreasing" if model.coef_[0] < 0 else "flat"
    return {
        "status": "forecast_ready",
        "model": "log-linear time-series regression",
        "data_confidence": "medium" if len(clean) >= 3 else "low",
        "historical_years": [int(y) for y in years],
        "historical_points": [p.__dict__ for p in clean],
        "forecast": forecasts,
        "historical_yoy_growth_percent": growth_rates,
        "forecast_yoy_growth_percent": forecast_growth,
        "trend": direction,
        "cagr_percent": round(float((prices[-1] / prices[0]) ** (1 / (years[-1] - years[0])) - 1) * 100, 2) if years[-1] > years[0] else 0.0,
        "log_rmse": round(residual, 4),
        "last_historical_price_per_sqft": round(float(prices[-1]), 2),
    }
