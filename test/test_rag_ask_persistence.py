import asyncio
import importlib
import sys
import types
from types import SimpleNamespace

from api.schemas.rag import RagAskRequest
from core.db.models import Message, MESSAGE_MODE_RAG, MESSAGE_SOURCE_RAG_ASK


def load_rag_module(monkeypatch):
    fake_datasets = types.ModuleType("datasets")
    monkeypatch.setitem(sys.modules, "datasets", fake_datasets)
    sys.modules.pop("api.routes.rag", None)
    return importlib.import_module("api.routes.rag")


class _FakeChatCompletions:
    async def create(self, **kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="knowledge answer"))],
        )


class _FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FakeChatCompletions())


async def _fake_embed_text(question, client=None):
    return [0.1, 0.2, 0.3]


def test_ask_knowledge_persists_messages_into_session(db_session, seeded_chat_context, monkeypatch):
    rag_module = load_rag_module(monkeypatch)

    fake_hits = [
        {
            "document_id": 1,
            "document_name": "manual.md",
            "chunk_id": 10,
            "chunk_index": 0,
            "source_page": 1,
            "source_section": "maintenance",
            "content": "Clean the brush and filter regularly.",
            "vector_score": 0.9,
            "keyword_score": 0.8,
            "final_score": 0.95,
            "score": 0.95,
        },
    ]

    monkeypatch.setattr(rag_module, "embed_text", _fake_embed_text)
    monkeypatch.setattr(rag_module, "get_llm_client", lambda: _FakeClient())
    monkeypatch.setattr(rag_module, "search_similar_chunks_by_embedding", lambda *args, **kwargs: fake_hits)
    monkeypatch.setattr(rag_module, "rerank_chunks", lambda question, hits, top_k=5: hits[:top_k])
    monkeypatch.setattr(rag_module, "build_context", lambda hits: "context block")
    monkeypatch.setattr(
        rag_module,
        "build_citations",
        lambda hits: [
            {
                "document_id": 1,
                "document_name": "manual.md",
                "chunk_id": 10,
                "chunk_index": 0,
                "source_page": 1,
                "source_section": "maintenance",
                "score": 0.95,
                "content": "Clean the brush and filter regularly.",
            },
        ],
    )

    payload = RagAskRequest(
        session_id=seeded_chat_context.session.id,
        question="How should I maintain the robot?",
        top_k=5,
        strict_mode=True,
        document_ids=[],
    )

    result = asyncio.run(
        rag_module.ask_knowledge(
            payload=payload,
            db=db_session,
            user=seeded_chat_context.user,
        )
    )

    messages = (
        db_session.query(Message)
        .filter(Message.session_id == seeded_chat_context.session.id)
        .order_by(Message.id.asc())
        .all()
    )

    assert result["data"].answer.startswith("knowledge answer")
    assert "manual.md" in result["data"].answer
    assert [message.role for message in messages] == ["user", "assistant"]
    assert [message.mode for message in messages] == [MESSAGE_MODE_RAG, MESSAGE_MODE_RAG]
    assert [message.source for message in messages] == [MESSAGE_SOURCE_RAG_ASK, MESSAGE_SOURCE_RAG_ASK]
    assert messages[0].content == "How should I maintain the robot?"
    assert messages[1].content.startswith("knowledge answer")
    assert "manual.md" in messages[1].content
