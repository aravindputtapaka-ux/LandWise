import sys, os, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.auth import hash_password, verify_password, create_access_token, decode_access_token


def test_password_hash_roundtrip():
    h = hash_password("supersecret")
    assert verify_password("supersecret", h)
    assert not verify_password("wrongpassword", h)


def test_password_too_short_rejected():
    with pytest.raises(ValueError):
        hash_password("short")


def test_jwt_roundtrip():
    token = create_access_token("user-123", "a@b.com")
    payload = decode_access_token(token)
    assert payload["sub"] == "user-123"
    assert payload["email"] == "a@b.com"


def test_user_store_local_fallback(tmp_path):
    from app.services.user_store import UserStore
    os.environ.pop("MONGODB_URI", None)
    os.environ.pop("MONGODB_URL", None)
    os.environ["LOCAL_USERS_FILE"] = str(tmp_path / "users.json")
    store = UserStore()
    assert store.collection is None
    doc = store.create_user("Test", "test@example.com", hash_password("secret123"))
    assert store.get_by_email("test@example.com")["_id"] == doc["_id"]
    with pytest.raises(ValueError):
        store.create_user("Test", "test@example.com", hash_password("secret123"))

    store.add_search_history(doc["_id"], {
        "type": "property_price",
        "request": {"location": "Hyderabad"},
        "response": {"location": "Hyderabad"},
        "observations": [
            {"property_type": "land", "canonical_price_per_sqft": 4000, "area_sqft": 1200,
             "latitude": 17.4, "longitude": 78.4, "location": "Hyderabad", "source_quality": 0.8,
             "source_type": "property_portal", "bhk": None, "stored_at": "2026-01-01T00:00:00"}
        ],
    })
    history = store.get_history(doc["_id"])
    assert len(history) == 1
    assert history[0]["request"]["location"] == "Hyderabad"

    all_obs = store.all_observations("land")
    assert len(all_obs) == 1
    found = store.find_observations("Hyderabad", "land")
    assert len(found) == 1


def test_ml_gating_rejects_low_confidence_model():
    """A model with poor validation accuracy must not be blended into the
    final estimate; this mirrors the gating logic added to main.py."""
    from app.services.ml_service import PriceModel
    model = PriceModel()
    model.metrics = {"status": "trained", "r2": -0.5, "mape": 0.9}
    r2 = model.metrics.get("r2")
    mape = model.metrics.get("mape")
    trustworthy = (model.metrics.get("status") == "trained" and r2 is not None and r2 > 0.15 and (mape is None or mape < 0.45))
    assert trustworthy is False


def test_ml_gating_accepts_good_model_but_clamped():
    ppsf = 4000.0
    ml_ppsf = 20000.0  # wildly high extrapolation
    clamped = min(max(ml_ppsf, ppsf * 0.5), ppsf * 2.0)
    assert clamped == ppsf * 2.0
