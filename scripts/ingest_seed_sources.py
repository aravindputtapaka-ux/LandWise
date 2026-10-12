import asyncio, json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"backend"))
from app.services.source_service import collect_from_urls
from app.services.storage import ObservationStore

async def main():
    urls=json.loads((ROOT/"backend/data/seed_sources.json").read_text(encoding="utf-8"))
    rows, usable=await collect_from_urls(urls,"land",None,"Huzurnagar, Suryapet, Telangana")
    for r in rows:
        r["location"]="Huzurnagar, Suryapet, Telangana"; r["property_type"]="land"
    n=ObservationStore().insert_many(rows)
    print(f"Inserted {n} observations from {len(usable)} usable sources")
    for u in usable: print("  ",u)
    print("Discovery-only/social pages with no structured evidence are intentionally skipped.")

if __name__ == "__main__": asyncio.run(main())
