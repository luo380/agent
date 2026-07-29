import json

import pytest

from core.config import settings
from core.db.models import DOCUMENT_STATUS_READY, KnowledgeChunks, KnowledgeDocuments, User
from core.service.retrieval import search_similar_chunks_by_embedding
from core.service.vector_index import rebuild_user_faiss_index


pytest.importorskip("faiss")


def test_search_similar_chunks_by_embedding_uses_faiss_index(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "FAISS_INDEX_DIR", str(tmp_path / "faiss_indexes"))

    user = User(
        email="faiss@example.com",
        name="FAISS User",
        password_hash="not-used",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    document = KnowledgeDocuments(
        user_id=user.id,
        name="faiss-manual.txt",
        file_path=str(tmp_path / "faiss-manual.txt"),
        file_type="txt",
        status=DOCUMENT_STATUS_READY,
        content_text="voice assistant support guide",
        chunk_count=2,
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    relevant_chunk = KnowledgeChunks(
        document_id=document.id,
        user_id=user.id,
        chunk_index=0,
        content="This product supports Google Assistant and Alexa.",
        source_page=None,
        source_section="",
        embedding_json=json.dumps([1.0, 0.0], ensure_ascii=False),
    )
    irrelevant_chunk = KnowledgeChunks(
        document_id=document.id,
        user_id=user.id,
        chunk_index=1,
        content="Clean the main brush regularly for better maintenance.",
        source_page=None,
        source_section="",
        embedding_json=json.dumps([0.0, 1.0], ensure_ascii=False),
    )
    db_session.add_all([relevant_chunk, irrelevant_chunk])
    db_session.commit()
    db_session.refresh(relevant_chunk)
    db_session.refresh(irrelevant_chunk)

    indexed_count = rebuild_user_faiss_index(db_session, user_id=user.id)

    results = search_similar_chunks_by_embedding(
        db_session,
        user_id=user.id,
        query_embedding=[0.99, 0.01],
        query_text="support voice assistant",
        top_k=2,
    )

    assert indexed_count == 2
    assert results[0].chunk_id == relevant_chunk.id
    assert results[0].vector_score > results[1].vector_score
    assert (tmp_path / "faiss_indexes" / f"user_{user.id}.faiss").exists()


def test_search_similar_chunks_by_embedding_rebuilds_missing_index_on_demand(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "FAISS_INDEX_DIR", str(tmp_path / "faiss_indexes"))

    user = User(
        email="faiss-rebuild@example.com",
        name="FAISS Rebuild User",
        password_hash="not-used",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    document = KnowledgeDocuments(
        user_id=user.id,
        name="faiss-rebuild.txt",
        file_path=str(tmp_path / "faiss-rebuild.txt"),
        file_type="txt",
        status=DOCUMENT_STATUS_READY,
        content_text="repair instructions",
        chunk_count=1,
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    chunk = KnowledgeChunks(
        document_id=document.id,
        user_id=user.id,
        chunk_index=0,
        content="Reset the robot by holding the power button for 5 seconds.",
        source_page=None,
        source_section="",
        embedding_json=json.dumps([0.0, 1.0], ensure_ascii=False),
    )
    db_session.add(chunk)
    db_session.commit()
    db_session.refresh(chunk)

    results = search_similar_chunks_by_embedding(
        db_session,
        user_id=user.id,
        query_embedding=[0.0, 1.0],
        query_text="reset power button",
        top_k=1,
    )

    assert results[0].chunk_id == chunk.id
    assert (tmp_path / "faiss_indexes" / f"user_{user.id}.faiss").exists()