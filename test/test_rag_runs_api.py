import importlib
import sys
import types
from datetime import datetime, timedelta, timezone

from core.db.models import Message, MESSAGE_MODE_RAG, MESSAGE_SOURCE_RAG_ASK
from core.service.rag_trace import complete_rag_step, create_rag_run, create_rag_step


def load_rag_module(monkeypatch):
    fake_datasets = types.ModuleType("datasets")
    monkeypatch.setitem(sys.modules, "datasets", fake_datasets)
    sys.modules.pop("api.routes.rag", None)
    return importlib.import_module("api.routes.rag")


def test_get_rag_run_detail_returns_steps_sorted_by_started_at(db_session, seeded_chat_context, monkeypatch):
    rag_module = load_rag_module(monkeypatch)

    run = create_rag_run(
        db_session,
        user_id=seeded_chat_context.user.id,
        question="How do I clean the robot?",
        top_k=5,
        strict_mode=True,
        document_ids=[11, 22],
    )

    later_step = create_rag_step(
        db_session,
        rag_run_id=run.id,
        step_type="rerank_chunks",
        step_name="Later Step",
        input_payload={"order": "later"},
    )
    earlier_step = create_rag_step(
        db_session,
        rag_run_id=run.id,
        step_type="embed_query",
        step_name="Earlier Step",
        input_payload={"order": "earlier"},
    )

    baseline = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
    later_step.started_at = baseline + timedelta(seconds=5)
    earlier_step.started_at = baseline
    db_session.commit()

    complete_rag_step(db_session, later_step, output_payload={"ok": True})
    complete_rag_step(db_session, earlier_step, output_payload={"ok": True})

    result = rag_module.get_rag_run_detail(
        run.id,
        db=db_session,
        user=seeded_chat_context.user,
    )

    assert result["data"].id == run.id
    assert result["data"].question == "How do I clean the robot?"
    assert [step.step_name for step in result["data"].steps] == ["Earlier Step", "Later Step"]


def test_get_session_returns_mode_and_source_for_rag_messages(db_session, seeded_chat_context, monkeypatch):
    session_module = importlib.import_module("api.routes.session")

    db_session.add_all(
        [
            Message(
                session_id=seeded_chat_context.session.id,
                role="user",
                content="question",
                mode=MESSAGE_MODE_RAG,
                source=MESSAGE_SOURCE_RAG_ASK,
            ),
            Message(
                session_id=seeded_chat_context.session.id,
                role="assistant",
                content="answer",
                mode=MESSAGE_MODE_RAG,
                source=MESSAGE_SOURCE_RAG_ASK,
            ),
        ]
    )
    db_session.commit()

    result = session_module.get_session(
        seeded_chat_context.session.id,
        db=db_session,
        user=seeded_chat_context.user,
    )

    assert [item.mode for item in result["data"]] == [MESSAGE_MODE_RAG, MESSAGE_MODE_RAG]
    assert [item.source for item in result["data"]] == [MESSAGE_SOURCE_RAG_ASK, MESSAGE_SOURCE_RAG_ASK]
