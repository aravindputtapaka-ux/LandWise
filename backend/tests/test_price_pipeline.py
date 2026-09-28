import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.price_parser import extract_observations
from app.services.source_service import search_historical_prices
from app.unit_utils import convert_price_per_unit


def test_explicit_price_per_sq_yard():
    rows = extract_observations("https://example.com", "Rate", "Open plot rate is ₹950 per sq yard")
    assert len(rows) == 1
    assert rows[0].price_per_unit == 950
    assert round(rows[0].canonical_price_per_sqft, 6) == round(950 / 9, 6)


def test_total_price_and_area_pair():
    rows = extract_observations("https://99acres.com/x", "Plot", "166 sq yd for ₹15 lakh")
    assert len(rows) == 1
    assert rows[0].price == 1_500_000
    assert rows[0].area == 166
    assert rows[0].area_unit == "sq yd"


def test_unrelated_numbers_are_not_prices():
    rows = extract_observations("https://example.com", "Page 2026", "Page 2026, phone 9876543210, 166 sq yd")
    assert rows == []


def test_price_unit_conversion_direction():
    assert convert_price_per_unit(4004, "sq ft", "acre") == 4004 * 43560
    assert round(convert_price_per_unit(950, "sq yd", "sq ft"), 6) == round(950 / 9, 6)


def test_search_historical_prices_handles_empty_rows_without_crashing():
    async def _run():
        with (
            patch(
                "app.services.source_service.tavily_search",
                AsyncMock(
                    return_value={
                        "results": [{
                            "url": "https://example.com/plot",
                            "title": "Land price",
                            "content": "2024 land price was ₹800 per sq ft",
                        }],
                        "usage": {},
                        "answer": "",
                    }
                ),
            ),
            patch(
                "app.services.source_service.fetch_url",
                AsyncMock(return_value=("Land price", "2024 land price was ₹800 per sq ft")),
            ),
        ):
            metadata, history = await search_historical_prices("Hyderabad", [2024])
            assert metadata["years"] == [2024]
            assert history

    asyncio.run(_run())
