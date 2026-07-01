from core.db.models import (
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_RUNNING,
    STEP_STATUS_COMPLETED,
    STEP_STATUS_FAILED,
    STEP_STATUS_RUNNING,
)
from core.service.run_trace import (
    complete_run,
    complete_step,
    create_run,
    create_step,
    dump_payload,
    fail_run,
    fail_step,
)


def test_dump_payload_handles_none_and_structured_data():
    assert dump_payload(None) == ""
    assert dump_payload({"step": "llm_call", "ok": True}) == '{"step": "llm_call", "ok": true}'


def test_create_and_complete_run_updates_status_and_output(db_session, seeded_chat_context):
    run = create_run(
        db_session,
        session_id=seeded_chat_context.session.id,
        agent_id=seeded_chat_context.agent.id,
        user_id=seeded_chat_context.user.id,
        input_text="hello trace",
    )

    assert run.status == RUN_STATUS_RUNNING
    assert run.input_text == "hello trace"
    assert run.started_at is not None
    assert run.finished_at is None

    completed = complete_run(db_session, run, output_text="trace completed")

    assert completed.status == RUN_STATUS_COMPLETED
    assert completed.output_text == "trace completed"
    assert completed.error_message == ""
    assert completed.finished_at is not None


def test_fail_run_persists_error_and_partial_output(db_session, seeded_chat_context):
    run = create_run(
        db_session,
        session_id=seeded_chat_context.session.id,
        agent_id=seeded_chat_context.agent.id,
        user_id=seeded_chat_context.user.id,
        input_text="trigger failure",
    )

    failed = fail_run(
        db_session,
        run,
        error_message="llm timeout",
        output_text="partial text",
    )

    assert failed.status == RUN_STATUS_FAILED
    assert failed.error_message == "llm timeout"
    assert failed.output_text == "partial text"
    assert failed.finished_at is not None


def test_create_complete_and_fail_step_record_payloads(db_session, seeded_chat_context):
    run = create_run(
        db_session,
        session_id=seeded_chat_context.session.id,
        agent_id=seeded_chat_context.agent.id,
        user_id=seeded_chat_context.user.id,
        input_text="step test",
    )

    step = create_step(
        db_session,
        run_id=run.id,
        step_type="build_messages",
        step_name="Build Model Messages",
        input_payload={"history_count": 3},
    )

    assert step.status == STEP_STATUS_RUNNING
    assert step.input_payload == '{"history_count": 3}'
    assert step.finished_at is None

    completed = complete_step(
        db_session,
        step,
        output_payload={"message_count": 4},
    )

    assert completed.status == STEP_STATUS_COMPLETED
    assert completed.output_payload == '{"message_count": 4}'
    assert completed.error_message == ""
    assert completed.finished_at is not None

    failed_step = create_step(
        db_session,
        run_id=run.id,
        step_type="stream_response",
        step_name="Receive Stream Response",
        input_payload={"stream": True},
    )

    failed = fail_step(
        db_session,
        failed_step,
        error_message="stream interrupted",
        output_payload={"partial_text": "hello"},
    )

    assert failed.status == STEP_STATUS_FAILED
    assert failed.error_message == "stream interrupted"
    assert failed.output_payload == '{"partial_text": "hello"}'
    assert failed.finished_at is not None
