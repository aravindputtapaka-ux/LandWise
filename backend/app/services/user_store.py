"""User account storage.

Replaces the old flat `market_observations` Mongo collection. Everything now
lives under a single `users` collection: each user document holds their
profile plus an embedded `search_history` array. Every search a user runs
(property-price or affordability) is appended to their own document together
with the full output that was returned to them, and the raw evidence rows
collected for that search (used later as ML training data).

Historical data for the ML model is therefore reconstructed on demand by
aggregating the `observations` embedded inside every user's search history
(across all users), instead of reading a separate collection.

A local JSON-file fallback mirrors the same shape when MongoDB is not
reachable, so the app keeps working offline / in dev.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Optional

try:
    from pymongo import MongoClient, ASCENDING
    from pymongo.errors import DuplicateKeyError
except Exception:
    MongoClient = None
    ASCENDING = 1
    class DuplicateKeyError(Exception):
        pass

MAX_HISTORY_PER_USER = 200


class UserStore:
    def __init__(self):
        self.mongo_uri = os.getenv("MONGODB_URI") or os.getenv("MONGODB_URL")
        self.db_name = os.getenv("MONGODB_DB", "landwise_ai")
        self.path = Path(os.getenv("LOCAL_USERS_FILE", "./data/users.json"))
        self.collection = None
        if self.mongo_uri and MongoClient:
            try:
                client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=4000)
                client.admin.command("ping")
                self.collection = client[self.db_name]["users"]
                self.collection.create_index([("email", ASCENDING)], unique=True)
            except Exception:
                self.collection = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")

    # ------------------------------------------------------------------
    # local JSON fallback helpers
    # ------------------------------------------------------------------
    def _load_local(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8") or "[]")
        except Exception:
            return []

    def _save_local(self, users: list[dict]) -> None:
        self.path.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # account management
    # ------------------------------------------------------------------
    def get_by_email(self, email: str) -> Optional[dict]:
        email = email.strip().lower()
        if self.collection is not None:
            try:
                return self.collection.find_one({"email": email})
            except Exception:
                pass
        for u in self._load_local():
            if u.get("email") == email:
                return u
        return None

    def get_by_id(self, user_id: str) -> Optional[dict]:
        if self.collection is not None:
            try:
                return self.collection.find_one({"_id": user_id})
            except Exception:
                pass
        for u in self._load_local():
            if u.get("_id") == user_id:
                return u
        return None

    def create_user(self, name: str, email: str, password_hash: str) -> dict:
        email = email.strip().lower()
        if self.get_by_email(email):
            raise ValueError("An account with this email already exists.")
        doc = {
            "_id": str(uuid.uuid4()),
            "name": name.strip(),
            "email": email,
            "password_hash": password_hash,
            "email_verified": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "search_history": [],
        }
        if self.collection is not None:
            try:
                self.collection.insert_one(dict(doc))
                return doc
            except DuplicateKeyError:
                raise ValueError("An account with this email already exists.")
            except Exception:
                pass
        users = self._load_local()
        users.append(doc)
        self._save_local(users)
        return doc


    def set_otp(self, user_id: str, otp_hash: str, expires_at: str, purpose: str) -> bool:
        fields = {
            "otp_hash": otp_hash,
            "otp_expires_at": expires_at,
            "otp_purpose": purpose,
            "otp_attempts": 0,
        }
        if self.collection is not None:
            try:
                return bool(self.collection.update_one({"_id": user_id}, {"$set": fields}).modified_count or self.collection.find_one({"_id": user_id}))
            except Exception:
                pass
        users = self._load_local()
        for u in users:
            if u.get("_id") == user_id:
                u.update(fields)
                self._save_local(users)
                return True
        return False

    def get_otp_state(self, user_id: str) -> Optional[dict]:
        u = self.get_by_id(user_id)
        if not u:
            return None
        return {k: u.get(k) for k in ("otp_hash", "otp_expires_at", "otp_purpose", "otp_attempts")}

    def clear_otp(self, user_id: str) -> bool:
        if self.collection is not None:
            try:
                self.collection.update_one({"_id": user_id}, {"$unset": {"otp_hash": "", "otp_expires_at": "", "otp_purpose": "", "otp_attempts": ""}})
                return True
            except Exception:
                pass
        users = self._load_local()
        for u in users:
            if u.get("_id") == user_id:
                for k in ("otp_hash", "otp_expires_at", "otp_purpose", "otp_attempts"):
                    u.pop(k, None)
                self._save_local(users)
                return True
        return False

    def increment_otp_attempts(self, user_id: str) -> int:
        if self.collection is not None:
            try:
                self.collection.update_one({"_id": user_id}, {"$inc": {"otp_attempts": 1}})
                res = self.collection.find_one({"_id": user_id}, {"otp_attempts": 1})
                return int((res or {}).get("otp_attempts", 0))
            except Exception:
                pass
        users = self._load_local()
        for u in users:
            if u.get("_id") == user_id:
                u["otp_attempts"] = int(u.get("otp_attempts", 0)) + 1
                value = u["otp_attempts"]
                self._save_local(users)
                return value
        return 0

    def mark_email_verified(self, user_id: str) -> bool:
        if self.collection is not None:
            try:
                self.collection.update_one({"_id": user_id}, {"$set": {"email_verified": True}})
                return True
            except Exception:
                pass
        users = self._load_local()
        for u in users:
            if u.get("_id") == user_id:
                u["email_verified"] = True
                self._save_local(users)
                return True
        return False

    def update_password(self, user_id: str, password_hash: str) -> bool:
        if self.collection is not None:
            try:
                self.collection.update_one({"_id": user_id}, {"$set": {"password_hash": password_hash}})
                return True
            except Exception:
                pass
        users = self._load_local()
        for u in users:
            if u.get("_id") == user_id:
                u["password_hash"] = password_hash
                self._save_local(users)
                return True
        return False

    # ------------------------------------------------------------------
    # search history (replaces market_observations writes)
    # ------------------------------------------------------------------
    def add_search_history(self, user_id: str, entry: dict) -> None:
        entry = dict(entry)
        entry.setdefault("id", str(uuid.uuid4()))
        entry.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        if self.collection is not None:
            try:
                self.collection.update_one(
                    {"_id": user_id},
                    {"$push": {"search_history": {"$each": [entry], "$position": 0, "$slice": MAX_HISTORY_PER_USER}}},
                )
                return
            except Exception:
                pass
        users = self._load_local()
        for u in users:
            if u.get("_id") == user_id:
                u.setdefault("search_history", []).insert(0, entry)
                u["search_history"] = u["search_history"][:MAX_HISTORY_PER_USER]
                break
        self._save_local(users)

    def get_history(self, user_id: str, limit: int = 50) -> list[dict]:
        user = self.get_by_id(user_id)
        if not user:
            return []
        return (user.get("search_history") or [])[:limit]

    def delete_history_item(self, user_id: str, item_id: str) -> bool:
        if self.collection is not None:
            try:
                res = self.collection.update_one({"_id": user_id}, {"$pull": {"search_history": {"id": item_id}}})
                return bool(res.modified_count)
            except Exception:
                pass
        users = self._load_local()
        changed = False
        for u in users:
            if u.get("_id") == user_id:
                before = len(u.get("search_history") or [])
                u["search_history"] = [h for h in (u.get("search_history") or []) if h.get("id") != item_id]
                changed = len(u["search_history"]) != before
                break
        if changed:
            self._save_local(users)
        return changed

    # ------------------------------------------------------------------
    # ML / comparable historical data, reconstructed from every user's
    # embedded search history (this is what used to live in the separate
    # `market_observations` collection).
    # ------------------------------------------------------------------
    def all_observations(self, property_type: str, bhk: str | None = None, limit: int = 10000) -> list[dict]:
        if self.collection is not None:
            try:
                match: dict[str, Any] = {"observations.property_type": property_type}
                pipeline = [
                    {"$unwind": "$search_history"},
                    {"$unwind": "$search_history.observations"},
                    {"$replaceRoot": {"newRoot": "$search_history.observations"}},
                    {"$match": {"property_type": property_type, **({"bhk": bhk} if bhk else {})}},
                    {"$sort": {"stored_at": -1}},
                    {"$limit": limit},
                ]
                return list(self.collection.aggregate(pipeline))
            except Exception:
                pass
        out = []
        for u in self._load_local():
            for h in u.get("search_history") or []:
                for o in h.get("observations") or []:
                    if o.get("property_type") != property_type:
                        continue
                    if bhk and o.get("bhk") != bhk:
                        continue
                    out.append(o)
                    if len(out) >= limit:
                        return out
        return out

    def find_observations(self, location: str, property_type: str, bhk: str | None = None, limit: int = 5000) -> list[dict]:
        if self.collection is not None:
            try:
                pipeline = [
                    {"$unwind": "$search_history"},
                    {"$unwind": "$search_history.observations"},
                    {"$replaceRoot": {"newRoot": "$search_history.observations"}},
                    {"$match": {
                        "property_type": property_type,
                        "location": {"$regex": location, "$options": "i"},
                        **({"bhk": bhk} if bhk else {}),
                    }},
                    {"$sort": {"stored_at": -1}},
                    {"$limit": limit},
                ]
                return list(self.collection.aggregate(pipeline))
            except Exception:
                pass
        out = []
        loc = location.lower()
        for u in self._load_local():
            for h in u.get("search_history") or []:
                for o in h.get("observations") or []:
                    if o.get("property_type") != property_type:
                        continue
                    if bhk and o.get("bhk") != bhk:
                        continue
                    if loc not in str(o.get("location") or "").lower() and loc not in str(o.get("evidence") or "").lower():
                        continue
                    out.append(o)
                    if len(out) >= limit:
                        return out
        return out
