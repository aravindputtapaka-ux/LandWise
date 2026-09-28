import json, os
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

try:
    from pymongo import MongoClient
except Exception:
    MongoClient = None

class ObservationStore:
    def __init__(self):
        self.mongo_uri = os.getenv("MONGODB_URI") or os.getenv("MONGODB_URL")
        self.db_name = os.getenv("MONGODB_DB", "landwise_ai")
        self.path = Path(os.getenv("LOCAL_DATA_FILE", "./data/market_observations.jsonl"))
        self.collection = None
        if self.mongo_uri and MongoClient:
            try:
                client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=3000)
                client.admin.command("ping")
                self.collection = client[self.db_name]["market_observations"]
            except Exception:
                self.collection = None
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def insert_many(self, rows: list[dict]) -> int:
        if not rows: return 0
        for r in rows:
            r.setdefault("stored_at", datetime.now(timezone.utc).isoformat())
        if self.collection is not None:
            try:
                self.collection.insert_many(rows, ordered=False)
                return len(rows)
            except Exception:
                pass
        with self.path.open("a", encoding="utf-8") as f:
            for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return len(rows)

    def all(self, property_type: str, bhk: str|None = None, limit: int = 10000) -> list[dict]:
        if self.collection is not None:
            q={"property_type":property_type}
            if bhk: q["bhk"]=bhk
            try:
                return list(self.collection.find(q,{"_id":0}).sort("stored_at",-1).limit(limit))
            except Exception:
                pass
        if not self.path.exists(): return []
        out=[]
        with self.path.open("r",encoding="utf-8") as f:
            for line in f:
                try: r=json.loads(line)
                except Exception: continue
                if r.get("property_type")!=property_type: continue
                if bhk and r.get("bhk")!=bhk: continue
                out.append(r)
                if len(out)>=limit: break
        return out

    def find(self, location: str, property_type: str, bhk: str|None = None, limit: int = 5000) -> list[dict]:
        if self.collection is not None:
            q = {"property_type": property_type, "location": {"$regex": location, "$options":"i"}}
            if bhk: q["bhk"] = bhk
            try: return [{k:v for k,v in doc.items() if k != "_id"} for doc in self.collection.find(q, {"_id":0}).sort("stored_at", -1).limit(limit)]
            except Exception: pass
        if not self.path.exists(): return []
        out=[]
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                try: r=json.loads(line)
                except Exception: continue
                if r.get("property_type") != property_type: continue
                if bhk and r.get("bhk") != bhk: continue
                if location.lower() not in str(r.get("location") or "").lower() and location.lower() not in str(r.get("evidence") or "").lower(): continue
                out.append(r)
                if len(out)>=limit: break
        return out
