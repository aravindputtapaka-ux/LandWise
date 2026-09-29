from __future__ import annotations

import math
import re
from datetime import datetime
from statistics import median
from typing import Any

import numpy as np
from sklearn.linear_model import BayesianRidge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.services.source_service import tavily_search, tavily_extract, SourceServiceError


HISTORY_PROMPT = "according to year wise give me past 4 years land prices per sq ft data in {Location} in tabular form"
CURRENT_PROMPT = "average land cost price per sqft in {Location}"


def completed_years() -> list[int]:
    year = datetime.now().year
    return list(range(year - 4, year))


def _number(value: str) -> float | None:
    try:
        return float(value.replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _normalise(text: str) -> str:
    text = (text or "").replace("\u00a0", " ").replace("₹", "₹")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _valid_price(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and 1 <= value <= 10_000_000


def _extract_year_value_pairs(text: str, years: list[int]) -> dict[int, float]:
    """Extract only year -> INR/sq-ft pairs from Tavily answer/snippets.

    The parser deliberately prefers table-shaped rows and explicit `per sq ft`
    statements. It does not treat an arbitrary number elsewhere in the page as
    a price. This is important because search pages contain years, phone numbers,
    property areas and listing totals alongside prices.
    """
    text = _normalise(text)
    if not text:
        return {}

    wanted = set(years)
    found: dict[int, list[float]] = {y: [] for y in years}

    # Markdown/HTML-like table rows: 2025 | ₹1,250 | ...
    for raw_line in re.split(r"\n|(?<=\|)\s*(?=\d{4}\b)", text):
        line = raw_line.strip(" |\t")
        if not line:
            continue
        ym = re.search(r"\b(20\d{2})\b", line)
        if not ym:
            continue
        year = int(ym.group(1))
        if year not in wanted:
            continue
        after = line[ym.end():]
        nums = re.findall(r"(?<!\d)(\d[\d,]*(?:\.\d+)?)(?!\d)", after)
        for raw in nums:
            value = _number(raw)
            if not _valid_price(value):
                continue
            # Ignore another year and likely area/count values when the row is
            # explicit about the unit. Otherwise accept the first non-year value.
            if value is not None and 1900 <= value <= 2100:
                continue
            if re.search(r"(?:₹|rs\.?|inr|per\s*sq\.?\s*ft|/\s*sq\.?\s*ft|sq\.?\s*ft)", after, re.I) or "|" in line:
                found[year].append(value)
                break

    # Explicit prose: "2025: ₹1,250 per sq ft" or "2025 - 1250/sqft".
    for year in years:
        pattern = rf"\b{year}\b\s*(?:[:|\-–—]|is|was|=)?\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)\s*(?:per|/)?\s*(?:sq\.?\s*ft|square\s*feet?)"
        for m in re.finditer(pattern, text, re.I):
            value = _number(m.group(1))
            if _valid_price(value):
                found[year].append(value)

    # Flattened table text: `2025 ₹1,250 2024 ₹1,100 ...`
    for year in years:
        pattern = rf"\b{year}\b(.{{0,100}}?)(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)"
        for m in re.finditer(pattern, text, re.I | re.S):
            value = _number(m.group(2))
            if _valid_price(value):
                found[year].append(value)

    # If the Tavily answer clearly declares a `Year | Price per sq ft` table,
    # accept a plain numeric cell after the year as a last resort.
    table_context = bool(re.search(r"year.{0,80}(?:price|rate).{0,80}sq\.?\s*ft", text, re.I | re.S))
    if table_context:
        for year in years:
            if found[year]:
                continue
            m = re.search(rf"\b{year}\b\s*[|:]?\s*([\d,]+(?:\.\d+)?)\b", text)
            if m:
                value = _number(m.group(1))
                if _valid_price(value) and not (1900 <= value <= 2100):
                    found[year].append(value)

    # Median multiple mentions from the same source to reduce duplicate/noisy
    # extraction when Tavily repeats a row in title + snippet + answer.
    return {year: float(median(values)) for year, values in found.items() if values}


def _collect_text(response: dict[str, Any]) -> tuple[str, list[str]]:
    chunks: list[str] = []
    urls: list[str] = []
    answer = response.get("answer")
    if isinstance(answer, str) and answer.strip():
        chunks.append(answer)
    for item in response.get("results") or []:
        if not isinstance(item, dict):
            continue
        for key in ("title", "content", "snippet", "raw_content"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                chunks.append(value)
        if item.get("url"):
            urls.append(str(item["url"]))
    return "\n".join(chunks), list(dict.fromkeys(urls))


async def tavily_historical_land_prices(location: str) -> dict[str, Any]:
    """Retrieve the four completed annual land-price points using Tavily only."""
    years = completed_years()
    query = HISTORY_PROMPT.format(Location=location)

    response = await tavily_search(
        query,
        max_results=8,
        search_depth="advanced",
        include_answer=True,
    )
    text, urls = _collect_text(response)

    prices = _extract_year_value_pairs(text, years)

    # A small second Tavily query is used only if the exact requested prompt did
    # not return enough year/value pairs. It remains Tavily-only and keeps the
    # same requested location/unit constraints.
    if len(prices) < 3 and urls:
        try:
            extracted = await tavily_extract(urls[:5], max_urls=5)
            extracted_chunks = []
            for item in extracted.get("results") or []:
                raw = item.get("raw_content") or item.get("content") or ""
                if raw:
                    extracted_chunks.append(raw)
                if item.get("url"):
                    urls.append(str(item["url"]))
            extracted_text = "\n".join(extracted_chunks)
            if extracted_text:
                text += "\n" + extracted_text
                prices.update(_extract_year_value_pairs(extracted_text, years))
        except Exception:
            pass

    if len(prices) < 3:
        fallback = (
            f"{location} historical land price per sq ft {years[0]} {years[1]} "
            f"{years[2]} {years[3]} year wise table INR"
        )
        second = await tavily_search(
            fallback,
            max_results=8,
            search_depth="advanced",
            include_answer=True,
        )
        text2, urls2 = _collect_text(second)
        prices.update(_extract_year_value_pairs(text2, years))
        text = text + "\n" + text2
        urls.extend(urls2)

    prices = {y: prices[y] for y in years if y in prices and _valid_price(prices[y])}
    history = [
        {"year": y, "price_per_sqft": round(prices[y], 2), "currency": "INR"}
        for y in years if y in prices
    ]

    return {
        "query": query,
        "years_requested": years,
        "historical_prices": history,
        "sources": list(dict.fromkeys(urls))[:20],
        "evidence_text": text[:40000],
        "source_count": len(set(urls)),
    }


def _clean_history(history: list[dict[str, Any]]) -> list[tuple[int, float]]:
    values: dict[int, float] = {}
    for row in history or []:
        try:
            year = int(row["year"])
            price = float(row["price_per_sqft"])
            if 1900 <= year <= 2100 and _valid_price(price):
                values[year] = price
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(values.items())


def forecast_with_ml(history: list[dict[str, Any]], horizon: int = 5) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Five-year positive forecast from the four annual Tavily observations.

    Bayesian Ridge is used on log(price) because the input is a tiny time series:
    a high-capacity tree model cannot learn a meaningful extrapolation from four
    points. A small-sample leave-one-out check is reported so the UI can expose
    model quality instead of claiming a fake accuracy percentage.
    """
    clean = _clean_history(history)
    if len(clean) < 3:
        return [], {"status": "insufficient_historical_points", "points": len(clean)}

    years = np.asarray([y for y, _ in clean], dtype=float)
    prices = np.asarray([p for _, p in clean], dtype=float)
    x = (years - years.mean()).reshape(-1, 1)
    y = np.log(prices)

    model = make_pipeline(StandardScaler(), BayesianRidge(alpha_1=1.0, alpha_2=1.0, lambda_1=1.0, lambda_2=1.0))
    model.fit(x, y)

    # Leave-one-out diagnostic. With four points this is only a diagnostic,
    # not a guarantee of future market accuracy.
    errors: list[float] = []
    for i in range(len(clean)):
        mask = np.ones(len(clean), dtype=bool)
        mask[i] = False
        loo = make_pipeline(StandardScaler(), BayesianRidge(alpha_1=1.0, alpha_2=1.0, lambda_1=1.0, lambda_2=1.0))
        loo.fit(x[mask], y[mask])
        pred = float(np.exp(loo.predict(x[i:i+1])[0]))
        actual = prices[i]
        if actual > 0:
            errors.append(abs(pred - actual) / actual)
    loo_mape = float(np.mean(errors)) if errors else None

    last_year = max(y for y, _ in clean)
    forecast_years = [last_year + i for i in range(1, horizon + 1)]
    fx = ((np.asarray(forecast_years, dtype=float) - years.mean()).reshape(-1, 1))
    raw = np.exp(model.predict(fx))

    # Guardrail against a mathematically explosive extrapolation. The model is
    # still the source of the prediction; this only prevents numerical runaway
    # from four noisy web points. The bound is anchored to the last observed
    # value and is deliberately wide.
    last_price = prices[-1]
    max_annual_growth = 0.35
    bounded = []
    previous = last_price
    for value in raw:
        value = float(value)
        upper = previous * (1.0 + max_annual_growth)
        lower = previous * (1.0 - 0.25)
        value = min(max(value, lower), upper)
        bounded.append(value)
        previous = value

    forecast = [
        {"year": year, "predicted_price_per_sqft": round(price, 2), "currency": "INR"}
        for year, price in zip(forecast_years, bounded)
    ]
    metrics = {
        "status": "trained",
        "algorithm": "Bayesian Ridge regression on log(price_per_sqft)",
        "historical_points": len(clean),
        "leave_one_out_mape": round(loo_mape, 4) if loo_mape is not None else None,
        "last_observed_year": last_year,
        "guardrail": "maximum 35% modeled year-over-year increase and 25% decrease",
    }
    return forecast, metrics
