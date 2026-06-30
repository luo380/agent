import json

from sqlalchemy.orm import Session

from core.db.models import (
    RAG_RUN_STATUS_COMPLETED,
    RAG_RUN_STATUS_FAILED,
    RAG_RUN_STATUS_RUNNING,
    RAG_STEP_STATUS_COMPLETED,
    RAG_STEP_STATUS_FAILED,
    RAG_STEP_STATUS_RUNNING,
    RagRuns,
    RagRunSteps,
    now,
)


def dump_payload(payload: dict | list | None) -> str:
    # 统一把结构化数据转成 JSON 字符串存库
    if payload is None:
        return ""
    return json.dumps(payload, ensure_ascii=False)


def create_rag_run(
    db: Session,
    *,
    user_id: int,
    question: str,
    top_k: int,
    strict_mode: bool,
    document_ids: list[int] | None = None,
) -> RagRuns:
    run = RagRuns(
        user_id=user_id,
        question=question,
        status=RAG_RUN_STATUS_RUNNING,
        top_k=top_k,
        strict_mode=1 if strict_mode else 0,
        document_scope_json=dump_payload(document_ids or []),
        started_at=now(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def complete_rag_run(
    db: Session,
    run: RagRuns,
    *,
    answer: str,
) -> RagRuns:
    run.status = RAG_RUN_STATUS_COMPLETED
    run.answer = answer
    run.error_message = ""
    run.finished_at = now()
    db.commit()
    db.refresh(run)
    return run


def fail_rag_run(
    db: Session,
    run: RagRuns,
    *,
    error_message: str,
    answer: str = "",
) -> RagRuns:
    run.status = RAG_RUN_STATUS_FAILED
    run.answer = answer
    run.error_message = error_message
    run.finished_at = now()
    db.commit()
    db.refresh(run)
    return run


def create_rag_step(
    db: Session,
    *,
    rag_run_id: int,
    step_type: str,
    step_name: str,
    input_payload: dict | list | None = None,
) -> RagRunSteps:
    step = RagRunSteps(
        rag_run_id=rag_run_id,
        step_type=step_type,
        step_name=step_name,
        status=RAG_STEP_STATUS_RUNNING,
        input_payload=dump_payload(input_payload),
        started_at=now(),
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def complete_rag_step(
    db: Session,
    step: RagRunSteps,
    *,
    output_payload: dict | list | None = None,
) -> RagRunSteps:
    step.status = RAG_STEP_STATUS_COMPLETED
    step.output_payload = dump_payload(output_payload)
    step.error_message = ""
    step.finished_at = now()
    db.commit()
    db.refresh(step)
    return step


def fail_rag_step(
    db: Session,
    step: RagRunSteps,
    *,
    error_message: str,
    output_payload: dict | list | None = None,
) -> RagRunSteps:
    step.status = RAG_STEP_STATUS_FAILED
    step.output_payload = dump_payload(output_payload)
    step.error_message = error_message
    step.finished_at = now()
    db.commit()
    db.refresh(step)
    return step