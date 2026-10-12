"""Run from backend: python ingest_knowledge.py [directory]
Only the local operator can publish shared knowledge; there is no public upload route.
"""
import os
import sys
import hashlib
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient


def main():
    load_dotenv()
    root = Path(sys.argv[1] if len(sys.argv) > 1 else 'knowledge').resolve()
    if not root.is_dir():
        raise SystemExit('Knowledge directory does not exist.')
    uri = os.getenv('MONGODB_URI') or os.getenv('MONGODB_URL')
    if not uri:
        raise SystemExit('Set MONGODB_URI first.')
    documents = []
    for path in sorted(root.rglob('*')):
        if path.suffix.lower() not in ('.txt', '.md') or not path.is_file():
            continue
        if path.stat().st_size > 1_000_000:
            raise SystemExit(f'File exceeds 1 MB: {path.name}')
        text = path.read_text(encoding='utf-8')
        words = text.split()
        for start in range(0, len(words), 300):
            chunk = ' '.join(words[start:start + 380])
            name = str(path.relative_to(root))
            key = hashlib.sha256(f'{name}:{start}'.encode()).hexdigest()
            documents.append({'id': 'doc:' + key, 'kind': 'document', 'title': name,
                              'text': chunk, 'urls': []})
    if len(documents) > 2000:
        raise SystemExit('This starter supports up to 2000 knowledge chunks; reduce the input.')
    if not documents:
        raise SystemExit('No UTF-8 .txt/.md content found; existing knowledge was not changed.')
    with MongoClient(uri, serverSelectionTimeoutMS=4000) as client:
        db = client[os.getenv('MONGODB_DB', 'landwise_ai')]
        # Build a staging collection, then atomically replace the old corpus.
        from uuid import uuid4
        stage = db['knowledge_staging_' + uuid4().hex]
        try:
            stage.insert_many(documents)
            stage.create_index('id', unique=True)
            stage.rename('knowledge_chunks', dropTarget=True)
        except Exception:
            stage.drop()
            raise
    print(f'Published {len(documents)} knowledge chunks. These documents are shared with all signed-in users.')


if __name__ == '__main__':
    main()
