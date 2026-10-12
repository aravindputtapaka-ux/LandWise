import asyncio
import os
from functools import lru_cache
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from app.auth import CurrentUser, get_current_user
from app.services.chat_store import ChatStore, public
from app.services.retrieval_service import (
    retrieve,
    wants_estimation_list,
    list_saved_estimations,
)
from app.services.gemini_service import generate, config

router = APIRouter()


class ConversationCreate(BaseModel):
    title: str = Field('Property conversation', min_length=1, max_length=100)
    selected_search_id: str | None = Field(None, max_length=100)


class MessageCreate(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    request_id: UUID

    @field_validator('message')
    @classmethod
    def clean(cls, value):
        if not value.strip():
            raise ValueError('Message cannot be blank')
        return value.strip()


@lru_cache(maxsize=1)
def connection():
    uri = os.getenv('MONGODB_URI') or os.getenv('MONGODB_URL')
    if not uri:
        raise HTTPException(503, 'Chat requires MONGODB_URI in backend/.env.')
    client = MongoClient(uri, serverSelectionTimeoutMS=4000, connectTimeoutMS=4000, socketTimeoutMS=10000)
    try:
        client.admin.command('ping')
        db = client[os.getenv('MONGODB_DB', 'landwise_ai')]
        return db, ChatStore(db)
    except Exception:
        client.close()
        raise


def chat_access(current: CurrentUser = Depends(get_current_user)):
    try:
        db, store = connection()
        if not db.users.find_one({'_id': current.user_id}, {'_id': 1}):
            raise HTTPException(401, 'Your account is not in MongoDB. Sign in to a MongoDB-backed account or migrate local users first.')
        return current.user_id, db, store
    except PyMongoError:
        raise HTTPException(503, 'MongoDB is unavailable. Start MongoDB and retry; chat is not saved to a fallback file.')


@router.get('/status')
def status(access=Depends(chat_access)):
    uid, db, store = access
    return {'database': 'connected', 'gemini_configured': bool(os.getenv('GEMINI_API_KEY') and os.getenv('GEMINI_MODEL')),
            'knowledge_chunks': db.knowledge_chunks.count_documents({}), 'retrieval': 'local TF-IDF + exact saved-search lookup'}


@router.post('/conversations')
def create(req: ConversationCreate, access=Depends(chat_access)):
    uid, db, store = access
    if req.selected_search_id:
        if not db.users.find_one({'_id': uid, 'search_history.id': req.selected_search_id}, {'_id': 1}):
            raise HTTPException(404, 'Saved search not found.')
    return store.create(uid, req.title.strip(), req.selected_search_id)


@router.get('/conversations')
def conversations(skip: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100), access=Depends(chat_access)):
    uid, db, store = access
    return store.list(uid, skip, limit)


@router.get('/conversations/{cid}/messages')
def messages(cid: str, skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), access=Depends(chat_access)):
    uid, db, store = access
    return store.page(uid, cid, skip, limit)


@router.delete('/conversations/{cid}')
def delete(cid: str, access=Depends(chat_access)):
    uid, db, store = access
    store.delete(uid, cid)
    return {'deleted': True}


@router.post('/conversations/{cid}/messages')
async def send(cid: str, req: MessageCreate, access=Depends(chat_access)):
    uid, db, store = access
    request_id = str(req.request_id)
    conversation = await asyncio.to_thread(store.owned, uid, cid)
    existing_user = await asyncio.to_thread(store.existing, uid, cid, request_id, 'user')
    if existing_user and existing_user['content'] != req.message:
        raise HTTPException(409, 'A request ID cannot be reused for a different message.')
    existing_answer = await asyncio.to_thread(store.existing, uid, cid, request_id, 'assistant')
    if existing_answer:
        return public(existing_answer)
    listing_requested = wants_estimation_list(req.message)
    
    if not listing_requested:
        config()  # Do not save a message when initial configuration is missing.

    lock_id = await asyncio.to_thread(store.lock, uid, cid)
    try:
        # Recheck under lock: a concurrent retry may have just completed.
        existing_answer = await asyncio.to_thread(store.existing, uid, cid, request_id, 'assistant')
        if existing_answer:
            return public(existing_answer)
        history = await asyncio.to_thread(store.page, uid, cid, 0, 12)
        history = [m for m in history if m.get('request_id') != request_id]
        await asyncio.to_thread(store.save, uid, cid, request_id, 'user', req.message)
        if listing_requested:
            answer = await asyncio.to_thread(
                list_saved_estimations,
                db,
                uid,
            )
            sources = []
        else:
            evidence, note = await asyncio.to_thread(
                retrieve,
                db,
                uid,
                req.message,
                history,
                conversation.get("selected_search_id"),
            )

            print("RAG evidence count:", len(evidence))
            print("RAG retrieval note:", note)
            print("Gemini model:", os.getenv("GEMINI_MODEL"))

            answer = await generate(
                req.message,
                history,
                evidence,
                note,
            )

            sources = [
                {k: record[k] for k in ("id", "kind", "title", "urls")}
                for record in evidence
            ]
        return await asyncio.to_thread(store.save, uid, cid, request_id, 'assistant', answer, sources)
    finally:
        await asyncio.to_thread(store.unlock, uid, cid, lock_id)
