import httpx

async def geocode(location: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=8, headers={"User-Agent":"LandWiseAI/1.0"}) as client:
            r=await client.get("https://nominatim.openstreetmap.org/search",params={"q":location,"format":"json","limit":1})
            r.raise_for_status(); data=r.json()
            if data: return {"lat":float(data[0]["lat"]),"lon":float(data[0]["lon"]),"display_name":data[0].get("display_name",location)}
    except Exception: pass
    return {}
