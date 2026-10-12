"""Mongo-only chat persistence. All private reads are scoped by user_id."""
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from fastapi import HTTPException


def now():
    return datetime.now(timezone.utc)


def public(doc):
    if doc is None:
        return None
    return {('id' if k == '_id' else k): (v.isoformat() if isinstance(v, datetime) else v)
            for k, v in doc.items() if k not in ('busy_until', 'lock_id')}


class ChatStore:
    def __init__(self, db):
        self.conversations = db.chat_conversations
        self.messages = db.chat_messages
        self.conversations.create_index([('user_id', ASCENDING), ('updated_at', DESCENDING)])
        self.messages.create_index([('user_id', ASCENDING), ('conversation_id', ASCENDING), ('sequence', ASCENDING)])
        self.messages.create_index([('user_id', ASCENDING), ('conversation_id', ASCENDING), ('request_id', ASCENDING), ('role', ASCENDING)], unique=True)

    def owned(self, uid, cid):
        doc = self.conversations.find_one({'_id': cid, 'user_id': uid})
        if not doc:
            raise HTTPException(404, 'Conversation not found.')
        return doc

    def create(self, uid, title, selected_search_id):
        doc = {'_id': str(uuid4()), 'user_id': uid, 'title': title,
               'selected_search_id': selected_search_id, 'created_at': now(), 'updated_at': now()}
        self.conversations.insert_one(doc.copy())
        return public(doc)

    def list(self, uid, skip, limit):
        return [public(d) for d in self.conversations.find({'user_id': uid}).sort('updated_at', -1).skip(skip).limit(limit)]

    def page(self, uid, cid, skip, limit):
        self.owned(uid, cid)
        # Fetch latest page descending, then return its messages chronologically.
        rows = list(self.messages.find({'user_id': uid, 'conversation_id': cid}).sort('sequence', -1).skip(skip).limit(limit))
        return [public(d) for d in reversed(rows)]

    def lock(self, uid, cid):
        self.owned(uid, cid)
        lock_id = str(uuid4())
        result = self.conversations.find_one_and_update(
            {'_id': cid, 'user_id': uid, '$or': [{'busy_until': {'$exists': False}}, {'busy_until': {'$lte': now()}}]},
            {'$set': {'busy_until': now() + timedelta(minutes=3), 'lock_id': lock_id}},
            return_document=ReturnDocument.AFTER)
        if not result:
            raise HTTPException(409, 'This conversation is answering another message. Please wait.')
        return lock_id

    def unlock(self, uid, cid, lock_id):
        self.conversations.update_one({'_id': cid, 'user_id': uid, 'lock_id': lock_id}, {'$unset': {'busy_until': '', 'lock_id': ''}})

    def existing(self, uid, cid, request_id, role):
        return self.messages.find_one({'user_id': uid, 'conversation_id': cid, 'request_id': request_id, 'role': role})

    def save(self, uid, cid, request_id, role, content, sources=None):
        key = {'user_id': uid, 'conversation_id': cid, 'request_id': request_id, 'role': role}
        existing = self.messages.find_one(key)
        if existing:
            return public(existing)
        parent = self.conversations.find_one_and_update(
            {'_id': cid, 'user_id': uid}, {'$inc': {'next_sequence': 1}},
            return_document=ReturnDocument.AFTER)
        if not parent:
            raise HTTPException(404, 'Conversation not found.')
        doc = {**key, '_id': str(uuid4()), 'content': content, 'sources': sources or [],
               'created_at': now(), 'sequence': parent['next_sequence']}
        self.messages.update_one(key, {'$setOnInsert': doc}, upsert=True)
        self.conversations.update_one({'_id': cid, 'user_id': uid}, {'$set': {'updated_at': now()}})
        return public(self.messages.find_one(key))

    def delete(self, uid, cid):
        lock_id = self.lock(uid, cid)
        try:
            self.messages.delete_many({'user_id': uid, 'conversation_id': cid})
            self.conversations.delete_one({'_id': cid, 'user_id': uid, 'lock_id': lock_id})
        finally:
            self.unlock(uid, cid, lock_id)
