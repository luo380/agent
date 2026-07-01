import asyncio
import json
from io import BytesIO

from fastapi import UploadFile

from api.routes import knowledge
from core.db.models import KnowledgeChunks, KnowledgeDocuments, DOCUMENT_STATUS_READY, User


async def _fake_embed_texts(texts, client=None):
    return [[float(index + 1), float(len(text))] for index, text in enumerate(texts)]


def test_upload_persists_chunk_embeddings(db_session, monkeypatch, tmp_path):
    user = User(
        email="kb@example.com",
        name="KB User",
        password_hash="not-used",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    monkeypatch.setattr(knowledge, "ensure_upload_dir", lambda: tmp_path)
    monkeypatch.setattr(knowledge, "parse_document", lambda file_path, file_type: {
        "full_text": "First paragraph. Second paragraph. Third paragraph. " * 40,
        "pages": [],
        "sections": [],
        "metadata": {},
    })
    monkeypatch.setattr(knowledge, "embed_texts", _fake_embed_texts)

    upload = UploadFile(filename="knowledge-test.txt", file=BytesIO("sample text".encode("utf-8")))
    response = asyncio.run(knowledge.upload_file(upload, db_session, user))

    document = db_session.query(KnowledgeDocuments).one()
    assert document.status == DOCUMENT_STATUS_READY
    assert document.chunk_count > 0
    assert response["data"].chunk_count == document.chunk_count

    chunks = db_session.query(KnowledgeChunks).order_by(KnowledgeChunks.chunk_index.asc()).all()
    assert len(chunks) == document.chunk_count
    assert all(chunk.embedding_json for chunk in chunks)

    first_embedding = json.loads(chunks[0].embedding_json)
    assert first_embedding[0] == 1.0
    assert len(first_embedding) == 2