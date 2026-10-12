from app.services.current_market import _collect_values


def test_market_range_parsing_sq_yard():
    rows = _collect_values("Current plot range ₹24,000 - ₹42,000 per sq yard")
    assert rows == [
        (24000.0, "sq yd", "range"),
        (42000.0, "sq yd", "range"),
    ]


def test_market_average_parsing_sq_yrd():
    rows = _collect_values("Average Price ₹/Sq-Yrd) ₹30644/Sq-Yrd")
    assert rows == [(30644.0, "sq yd", "average")]
