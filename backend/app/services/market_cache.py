"""Shared MongoDB cache of validated locality market estimates (not user history)."""
import time
import copy
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

from app.unit_utils import to_sqft, convert_price_per_unit

TTL_HOURS = max(1, int(os.getenv('MARKET_CACHE_TTL_HOURS', '24')))


def cache_key(req):
    if req.source_urls or req.currency.upper() != 'INR':
        return None  # Custom evidence must always be evaluated independently.
    # Never mix land, flats, BHK or property status.
    parts = [" ".join(req.location.casefold().split()), req.property_type,
             str(req.bhk or '').casefold(), str(req.property_status or '').casefold()]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def get(collection, key):
    if collection is None or key is None:
        return None
    doc = collection.find_one({'_id': key, 'expires_at': {'$gt': datetime.now(timezone.utc)}})
    return copy.deepcopy(doc['response']) if doc else None


def put(collection, key, response):
    if collection is None or key is None:
        return
    now = datetime.now(timezone.utc)
    clean = copy.deepcopy(response)
    clean.pop('search_id', None)
    collection.update_one({'_id': key}, {'$set': {
        'response': clean, 'updated_at': now,
        'expires_at': now + timedelta(hours=TTL_HOURS),
        'price_per_sqft': float(clean['average_price_per_sqft']),
    }}, upsert=True)


def for_area(cached, req):
    """Recalculate user-dependent totals; retain original evidence and per-sqft forecast."""
    result = copy.deepcopy(cached)
    rate = float(result['average_price_per_sqft'])
    unit = req.area_unit or 'sq ft'
    sqft = to_sqft(req.area, unit) if req.area else None
    result.update(location=req.location, property_type=req.property_type,
                  bhk=req.bhk, property_status=req.property_status,
                  unit=unit, price_per_unit=convert_price_per_unit(rate, 'sq ft', unit),
                  estimated_total_price=rate * sqft if sqft else None,
                  average_price=rate * sqft if sqft else None)
    # min_price/max_price are comparable listing prices, not user-area totals.
    result['source_summary'] = ('Cached locality market evidence (not a live quote); '
                                + result.get('source_summary', ''))
    return result



cached = None
start = time.perf_counter()

# Existing cache lookup happens here
# e.g. cached = get(collection, key)

elapsed_ms = (time.perf_counter() - start) * 1000

print(f"[CACHE] Lookup duration: {elapsed_ms:.0f} ms")
print(f"[CACHE] Result: {'HIT' if cached else 'MISS'}")