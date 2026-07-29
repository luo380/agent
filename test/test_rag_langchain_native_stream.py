import asyncio
import importlib

from sqlalchemy.orm import sessionmaker

from api.schemas.rag import RagAskRequest
from core.db.models import Message, MESSAGE_MODE_RAG, MESSAGE_SOURCE_RAG_ASK, RagRuns


async def _fake_stream_answer(*args, **kwargs):
    user_id = kwargs.get("user_id")
    strict_mode = kwargs.get("strict_mode")
    assert isinstance(user_id, int)

    yield {
        "event": "context_ready",
        "data": {
            "retrieved_chunk_count": 1,
            "citation_count": 1,
            "context_length": 12,
            "query_embedding_dim": 3,
        },
    }
    yield {
        "event": "done",
        "data": {
            "answer": "可以在线下门店或官方渠道购买。",
            "strict_mode": strict_mode,
            "citations": [],
            "retrieved_chunks": [],
            "context": "mock context",
            "query_embedding_dim": 3,
        },
    }


async def _collect_streaming_response(response):
    chunks = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8")
        chunks.append(chunk)
    return "".join(chunks)


def test_rag_langchain_stream_keeps_working_after_outer_session_closes(db_session, seeded_chat_context, monkeypatch):
    route_module = importlib.import_module("api.routes.rag_langchain_native")
    testing_session_local = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        future=True,
    )

    monkeypatch.setattr(route_module, "SessionLocal", testing_session_local)
    monkeypatch.setattr(route_module, "stream_answer_with_knowledge_langchain_native", _fake_stream_answer)

    session_id = seeded_chat_context.session.id

    payload = RagAskRequest(
        session_id=session_id,
        question="我可以从那里购买",
        top_k=5,
        strict_mode=True,
        document_ids=[],
    )

    response = asyncio.run(
        route_module.ask_knowledge_langchain_native_stream(
            payload=payload,
            db=db_session,
            user=seeded_chat_context.user,
        )
    )

    db_session.close()
    body = asyncio.run(_collect_streaming_response(response))

    verify_db = testing_session_local()
    try:
        messages = (
            verify_db.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.id.asc())
            .all()
        )
        rag_run = verify_db.query(RagRuns).order_by(RagRuns.id.desc()).first()
    finally:
        verify_db.close()

    assert "event: start" in body
    assert "event: context_ready" in body
    assert "event: done" in body
    assert "event: error" not in body
    assert [message.role for message in messages[-2:]] == ["user", "assistant"]
    assert [message.mode for message in messages[-2:]] == [MESSAGE_MODE_RAG, MESSAGE_MODE_RAG]
    assert [message.source for message in messages[-2:]] == [MESSAGE_SOURCE_RAG_ASK, MESSAGE_SOURCE_RAG_ASK]
    assert [message.strict_mode for message in messages[-2:]] == [1, 1]
    assert messages[-1].content == "可以在线下门店或官方渠道购买。"
    assert rag_run is not None
    assert rag_run.answer == "可以在线下门店或官方渠道购买。"
    assert rag_run.status == "completed"
