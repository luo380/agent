import asyncio
import json
from io import BytesIO

from fastapi import UploadFile

from api.routes import knowledge
from core.db.models import (
    DOCUMENT_STATUS_READY,
    KNOWLEDGE_CHUNK_ROLE_LEAF,
    KNOWLEDGE_CHUNK_ROLE_PARENT,
    KnowledgeChunks,
    KnowledgeDocuments,
    User,
)


async def _fake_aembed_documents(self, texts):
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
    monkeypatch.setattr(
        knowledge.ProjectDocumentLoader,
        "load_parsed_document",
        lambda self: {
            "full_text": "First paragraph. Second paragraph. Third paragraph. " * 40,
            "pages": [],
            "sections": [],
            "metadata": {},
        },
    )
    monkeypatch.setattr(knowledge.ProjectEmbeddings, "aembed_documents", _fake_aembed_documents)

    upload = UploadFile(filename="knowledge-test.txt", file=BytesIO("sample text".encode("utf-8")))
    response = asyncio.run(knowledge.upload_file(upload, db_session, user))

    document = db_session.query(KnowledgeDocuments).one()
    assert document.status == DOCUMENT_STATUS_READY
    assert document.chunk_count > 0
    assert response["data"].chunk_count == document.chunk_count

    chunks = db_session.query(KnowledgeChunks).order_by(KnowledgeChunks.chunk_index.asc()).all()
    assert len(chunks) == document.chunk_count

    parent_chunks = [chunk for chunk in chunks if chunk.chunk_role == KNOWLEDGE_CHUNK_ROLE_PARENT]
    leaf_chunks = [chunk for chunk in chunks if chunk.chunk_role == KNOWLEDGE_CHUNK_ROLE_LEAF]

    assert leaf_chunks
    assert all(chunk.embedding_json for chunk in leaf_chunks)
    assert all(not chunk.embedding_json for chunk in parent_chunks)

    first_embedding = json.loads(leaf_chunks[0].embedding_json)
    assert first_embedding[0] == 1.0
    assert len(first_embedding) == 2
