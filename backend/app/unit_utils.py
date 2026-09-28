UNIT_TO_SQFT = {
    "sq ft": 1.0,
    "sq yd": 9.0,
    "sq m": 10.7639104167,
    "acre": 43560.0,
    "hectare": 107639.104167,
    "cent": 435.6,
    "gunta": 1089.0,
    "marla": 272.25,
    # Bigha varies by jurisdiction. This value is deliberately flagged as approximate.
    "bigha": 27225.0,
}
ALIASES = {
    "sqft":"sq ft", "square foot":"sq ft", "square feet":"sq ft", "ft2":"sq ft", "ft²":"sq ft",
    "sqyd":"sq yd", "square yard":"sq yd", "square yards":"sq yd", "yd2":"sq yd", "yd²":"sq yd",
    "sqm":"sq m", "square meter":"sq m", "square meters":"sq m", "square metre":"sq m", "square metres":"sq m", "m2":"sq m", "m²":"sq m",
    "ac":"acre", "acres":"acre", "ha":"hectare", "hectares":"hectare",
    "cents":"cent", "guntas":"gunta", "marlas":"marla", "bighas":"bigha",
}

def normalize_unit(unit: str | None) -> str:
    if not unit:
        return "sq ft"
    v = str(unit).strip().lower().replace(".", "")
    return ALIASES.get(v, v)

def to_sqft(value: float, unit: str) -> float:
    u = normalize_unit(unit)
    if u not in UNIT_TO_SQFT:
        raise ValueError(f"Unsupported area unit: {unit}")
    return float(value) * UNIT_TO_SQFT[u]

def from_sqft(value: float, unit: str) -> float:
    u = normalize_unit(unit)
    if u not in UNIT_TO_SQFT:
        raise ValueError(f"Unsupported area unit: {unit}")
    return float(value) / UNIT_TO_SQFT[u]

def convert_area(value: float, from_unit: str, to_unit: str) -> float:
    return from_sqft(to_sqft(value, from_unit), to_unit)

def convert_price_per_unit(price: float, from_unit: str, to_unit: str) -> float:
    """Convert price/from_unit to price/to_unit without changing the economic amount."""
    from_factor = UNIT_TO_SQFT[normalize_unit(from_unit)]
    to_factor = UNIT_TO_SQFT[normalize_unit(to_unit)]
    # A price-per-unit is inversely proportional to unit size.
    # Example: ₹4,000/sq ft -> ₹4,000 * 43,560 = ₹174,240,000/acre.
    return float(price) * to_factor / from_factor

def build_equivalents(price_per_sqft: float) -> dict[str, float]:
    return {u: price_per_sqft * factor for u, factor in UNIT_TO_SQFT.items()}
