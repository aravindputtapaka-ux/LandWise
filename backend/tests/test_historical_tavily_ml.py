from app.services.historical_tavily import _extract_year_value_pairs, forecast_with_ml


def test_extract_markdown_history_table():
    text = """
    | Year | Price per sq ft |
    | 2022 | ₹500 |
    | 2023 | ₹550 |
    | 2024 | ₹620 |
    | 2025 | ₹700 |
    """
    assert _extract_year_value_pairs(text, [2022, 2023, 2024, 2025]) == {
        2022: 500.0,
        2023: 550.0,
        2024: 620.0,
        2025: 700.0,
    }


def test_forecast_is_positive_and_has_five_years():
    history = [
        {"year": 2022, "price_per_sqft": 500},
        {"year": 2023, "price_per_sqft": 550},
        {"year": 2024, "price_per_sqft": 620},
        {"year": 2025, "price_per_sqft": 700},
    ]
    forecast, metrics = forecast_with_ml(history, horizon=5)
    assert metrics["status"] == "trained"
    assert len(forecast) == 5
    assert [x["year"] for x in forecast] == [2026, 2027, 2028, 2029, 2030]
    assert all(x["predicted_price_per_sqft"] > 0 for x in forecast)
