import sys
from pathlib import Path
from uuid import uuid4
import pytest
import mongomock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.chat_store import ChatStore
from app.services.retrieval_service import retrieve
from app.routers import chat
from app.auth import CurrentUser, get_current_user


@pytest.fixture
def env(monkeypatch):
    db = mongomock.MongoClient().test
    db.users.insert_many([{'_id': 'alice', 'search_history': [{'id': 's1', 'type': 'property_price', 'created_at': '2026-01-01', 'request': {'location': 'Kodada', 'area': 1200}, 'response': {'estimated_total_price': 2424242}}]},
                          {'_id': 'bob', 'search_history': [{'id': 'secret', 'type': 'property_price', 'request': {'location': 'SecretTown'}, 'response': {}}]}])
    store = ChatStore(db)
    monkeypatch.setattr(chat, 'connection', lambda: (db, store))
    monkeypatch.setenv('GEMINI_API_KEY', 'test-only')
    monkeypatch.setenv('GEMINI_MODEL', 'test-model')
    app = FastAPI()
    app.include_router(chat.router, prefix='/chat')
    app.dependency_overrides[get_current_user] = lambda: CurrentUser('alice', 'alice@example.com')
    return TestClient(app), db, store, app


def test_persistence_and_user_isolation(env):
    client, db, store, app = env
    c = client.post('/chat/conversations', json={}).json()
    store.save('alice', c['id'], str(uuid4()), 'user', 'remember this')
    assert ChatStore(db).page('alice', c['id'], 0, 50)[0]['content'] == 'remember this'
    app.dependency_overrides[get_current_user] = lambda: CurrentUser('bob', 'bob@example.com')
    assert client.get(f"/chat/conversations/{c['id']}/messages").status_code == 404
    assert client.delete(f"/chat/conversations/{c['id']}").status_code == 404
    assert client.get('/chat/conversations').json() == []
    assert client.post('/chat/conversations', json={'selected_search_id': 's1'}).status_code == 404


def test_retrieval_scoped_and_missing_selection(env):
    client, db, store, app = env
    records, _ = retrieve(db, 'alice', 'SecretTown', [])
    assert not any(r['id'] == 'search:secret' for r in records)
    records, _ = retrieve(db, 'alice', 'explain it', [], 's1')
    assert records[0]['id'] == 'search:s1'
    records, note = retrieve(db, 'alice', 'latest', [], 'deleted')
    assert records == [] and note


def test_document_rag(env):
    _, db, _, _ = env
    db.knowledge_chunks.insert_one({'id': 'doc:1', 'kind': 'document', 'title': 'Help', 'text': 'Registration fees are excluded from affordability calculations.', 'urls': []})
    records, _ = retrieve(db, 'alice', 'Are registration fees included?', [])
    assert any(r['id'] == 'doc:1' for r in records)


def test_send_retry_idempotency_and_delete(env, monkeypatch):
    client, db, store, app = env
    calls = []
    async def generate(question, history, evidence, note):
        calls.append(question)
        return 'Your saved estimate was ₹24,24,242. [1]'
    monkeypatch.setattr(chat, 'generate', generate)
    c = client.post('/chat/conversations', json={'selected_search_id': 's1'}).json()
    path = f"/chat/conversations/{c['id']}/messages"
    req = {'message': 'Explain this estimate', 'request_id': str(uuid4())}
    first = client.post(path, json=req)
    assert first.status_code == 200
    assert client.post(path, json=req).json()['id'] == first.json()['id']
    assert len(calls) == 1
    assert len(client.get(path).json()) == 2
    assert client.post(path, json={**req, 'message': 'Different question'}).status_code == 409
    assert client.delete(f"/chat/conversations/{c['id']}").status_code == 200
    assert db.chat_messages.count_documents({}) == 0


def test_failure_can_be_retried_without_duplicate_user(env, monkeypatch):
    client, db, store, app = env
    async def fail(*args):
        raise HTTPException(504, 'Timeout')
    monkeypatch.setattr(chat, 'generate', fail)
    c = client.post('/chat/conversations', json={}).json()
    path = f"/chat/conversations/{c['id']}/messages"
    req = {'message': 'latest estimate', 'request_id': str(uuid4())}
    assert client.post(path, json=req).status_code == 504
    assert db.chat_messages.count_documents({}) == 1
    async def success(*args): return 'Saved estimate.'
    monkeypatch.setattr(chat, 'generate', success)
    assert client.post(path, json=req).status_code == 200
    assert db.chat_messages.count_documents({}) == 2


def test_lock_and_input_validation(env):
    client, db, store, _ = env
    c = client.post('/chat/conversations', json={}).json()
    lock = store.lock('alice', c['id'])
    assert client.post(f"/chat/conversations/{c['id']}/messages", json={'message': 'hello', 'request_id': str(uuid4())}).status_code == 409
    store.unlock('alice', c['id'], lock)
    assert client.post(f"/chat/conversations/{c['id']}/messages", json={'message': '   ', 'request_id': str(uuid4())}).status_code == 422


def test_pagination(env):
    _, _, store, _ = env
    c = store.create('alice', 'chat', None)
    for i in range(6): store.save('alice', c['id'], str(uuid4()), 'user', str(i))
    recent = store.page('alice', c['id'], 0, 3)
    older = store.page('alice', c['id'], 3, 3)
    assert [m['content'] for m in older + recent] == [str(i) for i in range(6)]

@pytest.mark.parametrize('finish,expected', [('STOP', 200), ('MAX_TOKENS', 502)])
def test_gemini_finish_reason_validation(monkeypatch, finish, expected):
    import asyncio
    import httpx
    from app.services import gemini_service as gemini
    monkeypatch.setenv('GEMINI_API_KEY', 'test-only')
    monkeypatch.setenv('GEMINI_MODEL', 'test-model')
    class FakeClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            assert 'x-goog-api-key' in kwargs['headers']
            return httpx.Response(200, request=httpx.Request('POST', url), json={'candidates': [{'finishReason': finish, 'content': {'parts': [{'text': 'answer'}]}}]})
    monkeypatch.setattr(gemini.httpx, 'AsyncClient', FakeClient)
    async def call():
        return await gemini.generate('question', [], [{'id': 's1', 'text': 'evidence'}])
    if expected == 200:
        assert asyncio.run(call()) == 'answer'
    else:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(call())
        assert exc.value.status_code == expected
