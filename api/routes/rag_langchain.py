# import json
#
# from fastapi import APIRouter, Depends, HTTPException
# from fastapi.responses import StreamingResponse
# from sqlalchemy.orm import Session
#
# from api.deps import get_current_user, get_db
# from api.schemas.rag import (
#     RagAskRequest,
#     RagAskResponse,
#     RagCitationResponse,
#     RagRetrievedChunkResponse,
# )
# from api.schemas.rag_run import RagRunDetailResponse, RagRunResponse, RagRunStepResponse
# from core.db.models import (
#     ChatSession,
#     Message,
#     MESSAGE_MODE_RAG,
#     MESSAGE_SOURCE_RAG_ASK,
#     RAG_STEP_STATUS_RUNNING,
#     RagRuns,
#     RagRunSteps,
#     User,
#     now,
# )
# from core.service.rag_langchain import (
#     stream_answer_with_knowledge_langchain,
# )
# from core.service.rag_trace import (
#     complete_rag_run,
#     complete_rag_step,
#     create_rag_run,
#     create_rag_step,
#     fail_rag_run,
#     fail_rag_step,
# )
#
# router = APIRouter()
#
#
# def fail_open_rag_step(db: Session, step_id: int | None, error_message: str) -> None:
#     if not step_id:
#         return
#
#     step = db.query(RagRunSteps).filter(RagRunSteps.id == step_id).first()
#     if step and step.status == RAG_STEP_STATUS_RUNNING:
#         fail_rag_step(db, step, error_message=error_message)
#
#
# def sse_event(event: str, data: dict) -> str:
#     return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
#
#
# @router.post("/ask")
# async def ask_knowledge_langchain(
#     payload: RagAskRequest,
#     db: Session = Depends(get_db),
#     user: User = Depends(get_current_user),
# ):
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
#             step_type="langchain_rag_answer",
#             step_name="Generate answer with LangChain RAG",
#             input_payload={
#                 "question_length": len(question),
#                 "top_k": payload.top_k,
#                 "strict_mode": payload.strict_mode,
#                 "document_ids": payload.document_ids,
#             },
#         )
#         step_answer_id = step_answer.id
#
#         result = await answer_with_knowledge_langchain(
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
#             step_type="langchain_format_citations",
#             step_name="Format LangChain citations",
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
#             detail=f"LangChain RAG ask failed: {error_message}",
#         )
#
#
#
#
# @router.post("/ask/stream")
# async def ask_knowledge_langchain_stream(
#     payload: RagAskRequest,
#     db: Session = Depends(get_db),
#     user: User = Depends(get_current_user),
# ):
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
#     async def event_generator():
#         step_answer = None
#         step_citation = None
#
#         try:
#             step_answer = create_rag_step(
#                 db,
#                 rag_run_id=rag_run.id,
#                 step_type="langchain_rag_stream",
#                 step_name="Generate streamed answer with LangChain RAG",
#                 input_payload={
#                     "question_length": len(question),
#                     "top_k": payload.top_k,
#                     "strict_mode": payload.strict_mode,
#                     "document_ids": payload.document_ids,
#                 },
#             )
#
#             yield sse_event(
#                 "start",
#                 {
#                     "run_id": rag_run.id,
#                     "strict_mode": payload.strict_mode,
#                     "top_k": payload.top_k,
#                 },
#             )
#
#             final_payload = None
#
#             async for event in stream_answer_with_knowledge_langchain(
#                 db,
#                 user_id=user.id,
#                 question=question,
#                 top_k=payload.top_k,
#                 document_ids=payload.document_ids or None,
#                 strict_mode=payload.strict_mode,
#             ):
#                 event_name = event["event"]
#                 data = event["data"]
#
#                 if event_name == "context_ready":
#                     yield sse_event("context_ready", data)
#                     continue
#
#                 if event_name == "delta":
#                     yield sse_event("delta", data)
#                     continue
#
#                 if event_name == "done":
#                     final_payload = data
#                     answer_text = final_payload["answer"]
#
#                     complete_rag_step(
#                         db,
#                         step_answer,
#                         output_payload={
#                             "answer_length": len(answer_text),
#                             "retrieved_chunk_count": len(final_payload["retrieved_chunks"]),
#                             "citation_count": len(final_payload["citations"]),
#                             "context_length": len(final_payload["context"]),
#                             "query_embedding_dim": final_payload["query_embedding_dim"],
#                         },
#                     )
#
#                     step_citation = create_rag_step(
#                         db,
#                         rag_run_id=rag_run.id,
#                         step_type="langchain_stream_citations",
#                         step_name="Format streamed LangChain citations",
#                         input_payload={"chunk_count": len(final_payload["retrieved_chunks"])},
#                     )
#                     complete_rag_step(
#                         db,
#                         step_citation,
#                         output_payload={"citation_count": len(final_payload["citations"])},
#                     )
#
#                     assistant_message = Message(
#                         session_id=session.id,
#                         role="assistant",
#                         content=answer_text,
#                         mode=MESSAGE_MODE_RAG,
#                         source=MESSAGE_SOURCE_RAG_ASK,
#                     )
#                     db.add(assistant_message)
#                     session.updated_at = now()
#                     db.commit()
#                     db.refresh(assistant_message)
#
#                     complete_rag_run(db, rag_run, answer=answer_text)
#
#                     final_payload["run_id"] = rag_run.id
#                     yield sse_event("done", final_payload)
#                     return
#
#         except Exception as exc:
#             error_message = str(exc)
#
#             if step_answer and step_answer.status == RAG_STEP_STATUS_RUNNING:
#                 fail_rag_step(db, step_answer, error_message=error_message)
#
#             if step_citation and step_citation.status == RAG_STEP_STATUS_RUNNING:
#                 fail_rag_step(db, step_citation, error_message=error_message)
#
#             latest_run = db.query(RagRuns).filter(RagRuns.id == rag_run.id).first()
#             if latest_run:
#                 fail_rag_run(db, latest_run, error_message=error_message)
#
#             yield sse_event(
#                 "error",
#                 {
#                     "message": f"LangChain RAG stream failed: {error_message}",
#                     "run_id": rag_run.id,
#                 },
#             )
#
#     return StreamingResponse(event_generator(), media_type="text/event-stream")
#
#
# @router.get("/run/{run_id}")
# def get_rag_langchain_run_detail(
#     run_id: int,
#     db: Session = Depends(get_db),
#     user: User = Depends(get_current_user),
# ):
#     rag_run = (
#         db.query(RagRuns)
#         .filter(RagRuns.id == run_id, RagRuns.user_id == user.id)
#         .first()
#     )
#
#     if not rag_run:
#         raise HTTPException(status_code=404, detail="RAG run not found")
#
#     steps = (
#         db.query(RagRunSteps)
#         .filter(RagRunSteps.rag_run_id == run_id)
#         .order_by(RagRunSteps.started_at.asc(), RagRunSteps.id.asc())
#         .all()
#     )
#
#     if not steps:
#         raise HTTPException(status_code=404, detail="No steps found")
#
#     data = RagRunDetailResponse(
#         **RagRunResponse.model_validate(rag_run).model_dump(),
#         steps=[RagRunStepResponse.model_validate(step) for step in steps],
#     )
#     return {"data": data}
#
#
# @router.get("/run/{run_id}")
# def get_rag_langchain_run_detail(
#     run_id: int,
#     db: Session = Depends(get_db),
#     user: User = Depends(get_current_user),
# ):
#     rag_run = (
#         db.query(RagRuns)
#         .filter(RagRuns.id == run_id, RagRuns.user_id == user.id)
#         .first()
#     )
#
#     if not rag_run:
#         raise HTTPException(status_code=404, detail="RAG run not found")
#
#     steps = (
#         db.query(RagRunSteps)
#         .filter(RagRunSteps.rag_run_id == run_id)
#         .order_by(RagRunSteps.started_at.asc(), RagRunSteps.id.asc())
#         .all()
#     )
#
#     if not steps:
#         raise HTTPException(status_code=404, detail="No steps found")
#
#     data = RagRunDetailResponse(
#         **RagRunResponse.model_validate(rag_run).model_dump(),
#         steps=[RagRunStepResponse.model_validate(step) for step in steps],
#     )
#     return {"data": data}