import importlib
import sys
import types
from datetime import datetime, timedelta, timezone

from core.service.run_trace import complete_step, create_run, create_step, fail_run


def load_runs_module(monkeypatch):
    fake_session_module = types.ModuleType("core.db.session")
    fake_session_module.SessionLocal = lambda: None

    monkeypatch.setitem(sys.modules, "core.db.session", fake_session_module)
    sys.modules.pop("api.deps", None)
    sys.modules.pop("api.routes.runs", None)

    return importlib.import_module("api.routes.runs")


def test_get_session_history_returns_latest_run(db_session, seeded_chat_context, monkeypatch):
    runs_module = load_runs_module(monkeypatch)

    older_run = create_run(
        db_session,
        session_id=seeded_chat_context.session.id,
        agent_id=seeded_chat_context.agent.id,
        user_id=seeded_chat_context.user.id,
        input_text="older",
    )
    fail_run(db_session, older_run, error_message="older failure")

    latest_run = create_run(
        db_session,
        session_id=seeded_chat_context.session.id,
        agent_id=seeded_chat_context.agent.id,
        user_id=seeded_chat_context.user.id,
        input_text="latest",
    )

    result = runs_module.get_session_history(
        str(seeded_chat_context.session.id),
        db=db_session,
        user=seeded_chat_context.user,
    )

    assert result["data"].id == latest_run.id
    assert result["data"].input_text == "latest"


def test_get_run_detail_returns_steps_sorted_by_started_at(db_session, seeded_chat_context, monkeypatch):
    runs_module = load_runs_module(monkeypatch)

    run = create_run(
        db_session,
        session_id=seeded_chat_context.session.id,
        agent_id=seeded_chat_context.agent.id,
        user_id=seeded_chat_context.user.id,
        input_text="sort my steps",
    )

    later_step = create_step(
        db_session,
        run_id=run.id,
        step_type="llm_call",
        step_name="Later Step",
        input_payload={"order": "later"},
    )
    earlier_step = create_step(
        db_session,
        run_id=run.id,
        step_type="build_messages",
        step_name="Earlier Step",
        input_payload={"order": "earlier"},
    )

    baseline = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
    later_step.started_at = baseline + timedelta(seconds=5)
    earlier_step.started_at = baseline
    db_session.commit()

    complete_step(db_session, later_step, output_payload={"ok": True})
    complete_step(db_session, earlier_step, output_payload={"ok": True})

    result = runs_module.get_run_detail(
        str(run.id),
        db=db_session,
        user=seeded_chat_context.user,
    )

    assert [step.step_name for step in result["data"].steps] == ["Earlier Step", "Later Step"]
    assert [step.step_type for step in result["data"].steps] == ["build_messages", "llm_call"]
