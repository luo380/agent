import importlib

from core.service.langchain_adapters import ProjectEmbeddings, ProjectKnowledgeRetriever


def test_build_langchain_retriever_returns_project_retriever(db_session, seeded_chat_context):
    service_module = importlib.import_module("core.service.rag_langchain_native")

    retriever = service_module.build_langchain_retriever(
        db_session,
        user_id=seeded_chat_context.user.id,
        top_k=7,
        document_ids=[11, 22],
        client=object(),
        candidate_multiplier=4,
    )

    assert isinstance(retriever, ProjectKnowledgeRetriever)
    assert retriever.db is db_session
    assert retriever.user_id == seeded_chat_context.user.id
    assert retriever.top_k == 7
    assert retriever.candidate_multiplier == 4
    assert retriever.document_ids == [11, 22]
    assert isinstance(retriever.embeddings, ProjectEmbeddings)
    assert retriever.embeddings.client is not None


class _FakeRetriever:
    def __init__(self):
        self.last_reranked_hits = []
        self.last_query_embedding_dim = 4

    async def aretrieve_documents(self, question):
        return []


def test_stream_answer_uses_retriever_aretrieve_documents(monkeypatch):
    import asyncio
    import importlib

    service_module = importlib.import_module("core.service.rag_langchain_native")
    fake_retriever = _FakeRetriever()

    monkeypatch.setattr(service_module, "build_langchain_retriever", lambda *args, **kwargs: fake_retriever)

    async def collect_events():
        events = []
        async for event in service_module.stream_answer_with_knowledge_langchain_native(
            db=object(),
            user_id=1,
            question="从哪里购买",
            strict_mode=True,
        ):
            events.append(event)
        return events

    events = asyncio.run(collect_events())

    assert [event["event"] for event in events] == ["context_ready", "done"]
    assert events[0]["data"]["query_embedding_dim"] == 4
