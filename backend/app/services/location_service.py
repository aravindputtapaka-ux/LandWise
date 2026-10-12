import asyncio
import time
from collections import OrderedDict

import httpx

_cache = OrderedDict()
_cache_lock = asyncio.Lock()


async def geocode(location: str) -> dict:
    key = " ".join(location.casefold().split())
    async with _cache_lock:
        cached = _cache.get(key)
        if cached and cached[0] > time.monotonic():
            _cache.move_to_end(key)
            return dict(cached[1])
    result = await _geocode_uncached(location)
    async with _cache_lock:
        _cache[key] = (time.monotonic() + (86400 if result else 300), result)
        _cache.move_to_end(key)
        if len(_cache) > 500:
            _cache.popitem(last=False)
    return dict(result)


async def _geocode_uncached(location: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=8, headers={"User-Agent":"LandWiseAI/1.0"}) as client:
            r=await client.get("https://nominatim.openstreetmap.org/search",params={"q":location,"format":"json","limit":1})
            r.raise_for_status(); data=r.json()
            if data: return {"lat":float(data[0]["lat"]),"lon":float(data[0]["lon"]),"display_name":data[0].get("display_name",location)}
    except Exception: pass
    return {}
