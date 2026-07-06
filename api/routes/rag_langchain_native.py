import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.schemas.rag import (
    RagAskRequest,
    RagAskResponse,
    RagCitationResponse,
    RagRetrievedChunkResponse,
)
from api.schemas.rag_run import RagRunDetailResponse, RagRunResponse, RagRunStepResponse
from core.db.models import (
    ChatSession,
    Message,
    MESSAGE_MODE_RAG,
    MESSAGE_SOURCE_RAG_ASK,
    RAG_STEP_STATUS_RUNNING,
    RagRuns,
    RagRunSteps,
    User,
    now,
)
from core.db.session import SessionLocal
from core.service.rag_langchain_native import (
    stream_answer_with_knowledge_langchain_native,
)
from core.service.rag_trace import (
    complete_rag_run,
    complete_rag_step,
    create_rag_run,
    create_rag_step,
    fail_rag_run,
    fail_rag_step,
)

router = APIRouter()


def fail_open_rag_step(db: Session, step_id: int | None, error_message: str) -> None:
    """
    异常兜底：如果某个 step 还处于 running，就标记为 failed。
    """
    if not step_id:
        return

    step = db.query(RagRunSteps).filter(RagRunSteps.id == step_id).first()
    if step and step.status == RAG_STEP_STATUS_RUNNING:
        fail_rag_step(db, step, error_message=error_message)


def sse_event(event: str, data: dict) -> str:
    """
    把事件包装成 SSE 格式。

    前端按空行分隔事件块：
    event: delta
    data: {"content":"你好"}
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

#
# @router.post("/ask")
# async def ask_knowledge_langchain_native(
#     payload: RagAskRequest,
#     db: Session = Depends(get_db),
#     user: User = Depends(get_current_user),
# ):
#     """
#     LangChain 原生非流式 RAG 接口。
#
#     用途：
#     - 保留普通 JSON 返回能力
#     - 方便和流式接口做对比
#     """
#     question = payload.question.strip()
#     if not question:
#         raise HTTPException(status_code=400, detail="Question is empty")
#
#     session = (
#         db.query(ChatSession)
#         .filter(ChatSession.id == payload.session_id, ChatSession.user_id == user.id)
#         .first()
#     )
#     if not session:
#         raise HTTPException(status_code=404, detail="Session not found")
#
#     user_message = Message(
#         session_id=session.id,
#         role="user",
#         content=question,
#         mode=MESSAGE_MODE_RAG,
#         source=MESSAGE_SOURCE_RAG_ASK,
#     )
#     db.add(user_message)
#     session.updated_at = now()
#     db.commit()
#     db.refresh(user_message)
#
#     rag_run = create_rag_run(
#         db,
#         user_id=user.id,
#         question=question,
#         top_k=payload.top_k,
#         strict_mode=payload.strict_mode,
#         document_ids=payload.document_ids,
#     )
#
#     step_answer_id = None
#     step_citation_id = None
#
#     try:
#         step_answer = create_rag_step(
#             db,
#             rag_run_id=rag_run.id,
#             step_type="langchain_native_rag_answer",
#             step_name="Generate answer with native LangChain RAG",
#             input_payload={
#                 "question_length": len(question),
#                 "top_k": payload.top_k,
#                 "strict_mode": payload.strict_mode,
#                 "document_ids": payload.document_ids,
#             },
#         )
#         step_answer_id = step_answer.id
#
#         result = await answer_with_knowledge_langchain_native(
#             db,
#             user_id=user.id,
#             question=question,
#             top_k=payload.top_k,
#             document_ids=payload.document_ids or None,
#             strict_mode=payload.strict_mode,
#         )
#
#         answer_text = result["answer"]
#         retrieved_chunks = result["retrieved_chunks"]
#         citations = result["citations"]
#         context = result["context"]
#
#         complete_rag_step(
#             db,
#             step_answer,
#             output_payload={
#                 "answer_length": len(answer_text),
#                 "retrieved_chunk_count": len(retrieved_chunks),
#                 "citation_count": len(citations),
#                 "context_length": len(context),
#                 "query_embedding_dim": result["query_embedding_dim"],
#             },
#         )
#
#         step_citation = create_rag_step(
#             db,
#             rag_run_id=rag_run.id,
#             step_type="langchain_native_format_citations",
#             step_name="Format native LangChain citations",
#             input_payload={"chunk_count": len(retrieved_chunks)},
#         )
#         step_citation_id = step_citation.id
#
#         complete_rag_step(
#             db,
#             step_citation,
#             output_payload={"citation_count": len(citations)},
#         )
#
#         assistant_message = Message(
#             session_id=session.id,
#             role="assistant",
#             content=answer_text,
#             mode=MESSAGE_MODE_RAG,
#             source=MESSAGE_SOURCE_RAG_ASK,
#         )
#         db.add(assistant_message)
#         session.updated_at = now()
#         db.commit()
#         db.refresh(assistant_message)
#
#         complete_rag_run(db, rag_run, answer=answer_text)
#
#         response = RagAskResponse(
#             question=question,
#             answer=answer_text,
#             run_id=rag_run.id,
#             strict_mode=payload.strict_mode,
#             citations=[RagCitationResponse.model_validate(item) for item in citations],
#             retrieved_chunks=[
#                 RagRetrievedChunkResponse.model_validate(item) for item in retrieved_chunks
#             ],
#         )
#         return {"data": response}
#
#     except Exception as exc:
#         error_message = str(exc)
#
#         for step_id in [step_answer_id, step_citation_id]:
#             fail_open_rag_step(db, step_id, error_message)
#
#         latest_run = db.query(RagRuns).filter(RagRuns.id == rag_run.id).first()
#         if latest_run:
#             fail_rag_run(db, latest_run, error_message=error_message)
#
#         raise HTTPException(
#             status_code=500,
#             detail=f"Native LangChain RAG ask failed: {error_message}",
#         )


@router.post("/ask/stream")
async def ask_knowledge_langchain_native_stream(
    payload: RagAskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    LangChain 原生流式 RAG 接口。
    路由层流程图：
    前端 POST /api/rag-langchain/ask/stream
      |
      v
    校验 session / 保存用户消息 / 创建 rag_run
      |
      v
    stream_answer_with_knowledge_langchain_native(...)
      |
      v
    context_ready / delta / done / error
      |
      v
    StreamingResponse(text/event-stream)

    核心点：
    - service 层使用 chain.astream(...)
    - route 层只负责把事件转成 SSE
    """
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is empty")

    user_id = user.id
    request_top_k = payload.top_k
    request_strict_mode = payload.strict_mode
    request_document_ids = list(payload.document_ids or [])

    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == payload.session_id, ChatSession.user_id == user_id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session_id = session.id
    user_message = Message(
        session_id=session_id,
        role="user",
        content=question,
        mode=MESSAGE_MODE_RAG,
        source=MESSAGE_SOURCE_RAG_ASK,
    )
    db.add(user_message)
    session.updated_at = now()
    db.commit()
    db.refresh(user_message)

    rag_run = create_rag_run(
        db,
        user_id=user_id,
        question=question,
        top_k=request_top_k,
        strict_mode=request_strict_mode,
        document_ids=request_document_ids,
    )
    rag_run_id = rag_run.id

    async def event_generator():
        inner_db = SessionLocal()
        step_answer = None
        step_answer_id = None
        step_citation = None
        step_citation_id = None

        try:
            step_answer = create_rag_step(
                inner_db,
                rag_run_id=rag_run_id,
                step_type="langchain_native_rag_stream",
                step_name="Generate streamed answer with native LangChain RAG",
                input_payload={
                    "question_length": len(question),
                    "top_k": request_top_k,
                    "strict_mode": request_strict_mode,
                    "document_ids": request_document_ids,
                },
            )
            step_answer_id = step_answer.id

            yield sse_event(
                "start",
                {
                    "run_id": rag_run_id,
                    "strict_mode": request_strict_mode,
                    "top_k": request_top_k,
                },
            )

            async for event in stream_answer_with_knowledge_langchain_native(
                inner_db,
                user_id=user_id,
                question=question,
                top_k=request_top_k,
                document_ids=request_document_ids or None,
                strict_mode=request_strict_mode,
            ):
                event_name = event["event"]
                data = event["data"]

                if event_name == "context_ready":
                    yield sse_event("context_ready", data)
                    continue

                if event_name == "delta":
                    yield sse_event("delta", data)
                    continue

                if event_name == "done":
                    answer_text = data["answer"]

                    complete_rag_step(
                        inner_db,
                        step_answer,
                        output_payload={
                            "answer_length": len(answer_text),
                            "retrieved_chunk_count": len(data["retrieved_chunks"]),
                            "citation_count": len(data["citations"]),
                            "context_length": len(data["context"]),
                            "query_embedding_dim": data["query_embedding_dim"],
                        },
                    )

                    step_citation = create_rag_step(
                        inner_db,
                        rag_run_id=rag_run_id,
                        step_type="langchain_native_stream_citations",
                        step_name="Format streamed native LangChain citations",
                        input_payload={"chunk_count": len(data["retrieved_chunks"])} ,
                    )
                    step_citation_id = step_citation.id
                    complete_rag_step(
                        inner_db,
                        step_citation,
                        output_payload={"citation_count": len(data["citations"])} ,
                    )

                    assistant_message = Message(
                        session_id=session_id,
                        role="assistant",
                        content=answer_text,
                        mode=MESSAGE_MODE_RAG,
                        source=MESSAGE_SOURCE_RAG_ASK,
                    )
                    inner_db.add(assistant_message)
                    inner_session = inner_db.query(ChatSession).filter(ChatSession.id == session_id).first()
                    if inner_session:
                        inner_session.updated_at = now()
                    inner_db.commit()
                    inner_db.refresh(assistant_message)

                    latest_run = inner_db.query(RagRuns).filter(RagRuns.id == rag_run_id).first()
                    if latest_run:
                        complete_rag_run(inner_db, latest_run, answer=answer_text)

                    data["run_id"] = rag_run_id
                    yield sse_event("done", data)
                    return

        except Exception as exc:
            error_message = str(exc)

            fail_open_rag_step(inner_db, step_answer_id, error_message)
            fail_open_rag_step(inner_db, step_citation_id, error_message)

            latest_run = inner_db.query(RagRuns).filter(RagRuns.id == rag_run_id).first()
            if latest_run:
                fail_rag_run(inner_db, latest_run, error_message=error_message)

            yield sse_event(
                "error",
                {
                    "message": f"Native LangChain RAG stream failed: {error_message}",
                    "run_id": rag_run_id,
                },
            )

        finally:
            inner_db.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/run/{run_id}")
def get_rag_langchain_native_run_detail(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    查询 LangChain RAG run 详情。

    仍然复用 RagRuns / RagRunSteps 表。
    这样你可以在同一套 trace UI 里对比不同 RAG 实现。
    """
    rag_run = (
        db.query(RagRuns)
        .filter(RagRuns.id == run_id, RagRuns.user_id == user.id)
        .first()
    )

    if not rag_run:
        raise HTTPException(status_code=404, detail="RAG run not found")

    steps = (
        db.query(RagRunSteps)
        .filter(RagRunSteps.rag_run_id == run_id)
        .order_by(RagRunSteps.started_at.asc(), RagRunSteps.id.asc())
        .all()
    )

    if not steps:
        raise HTTPException(status_code=404, detail="No steps found")

    data = RagRunDetailResponse(
        **RagRunResponse.model_validate(rag_run).model_dump(),
        steps=[RagRunStepResponse.model_validate(step) for step in steps],
    )
    return {"data": data}
