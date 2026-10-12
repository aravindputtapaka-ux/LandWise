"""Explicit one-time migration; never overwrites Mongo accounts. Back up both stores first."""
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient


def main():
    load_dotenv()
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python migrate_local_users.py path/to/users.json')
    source = Path(sys.argv[1])
    rows = json.loads(source.read_text(encoding='utf-8'))
    if not isinstance(rows, list) or any(not isinstance(r, dict) or not all(r.get(k) for k in ('_id', 'email', 'password_hash')) for r in rows):
        raise SystemExit('Not a valid LandWise users.json file.')
    uri = os.getenv('MONGODB_URI') or os.getenv('MONGODB_URL')
    if not uri:
        raise SystemExit('Set MONGODB_URI.')
    copied = skipped = 0
    with MongoClient(uri, serverSelectionTimeoutMS=4000) as client:
        users = client[os.getenv('MONGODB_DB', 'landwise_ai')].users
        users.create_index('email', unique=True)
        for row in rows:
            if users.find_one({'$or': [{'_id': row['_id']}, {'email': row['email']}]}, {'_id': 1}):
                skipped += 1
                continue
            users.insert_one(row)
            copied += 1
    print(f'Migrated {copied} accounts; skipped {skipped} existing/conflicting accounts. Source file unchanged.')


if __name__ == '__main__':
    main()
