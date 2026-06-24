import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.schemas.session import (
    MessageCreateRequest,
    MessageResponse,
    SessionCreateRequest,
    SessionResponse,
)
from core.db.models import Agent, ChatSession, Message, User, DEFAULT_SESSION_TITLE, now
from core.db.session import SessionLocal
from core.service.llm import get_default_model, get_llm_client

router = APIRouter()


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post('/create_session')
def create_session(
    payload: SessionCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = (
        db.query(Agent)
        .filter(Agent.id == payload.agent_id, Agent.created_by == user.id)
        .first()
    )
    if not agent:
        raise HTTPException(status_code=400, detail='Invalid agent id')

    session = ChatSession(
        title=payload.title.strip() or DEFAULT_SESSION_TITLE,
        agent_id=payload.agent_id,
        user_id=user.id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return {'data': SessionResponse.model_validate(session)}


@router.get('/list_sessions')
def list_sessions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        .all()
    )
    return {'data': [SessionResponse.model_validate(session) for session in sessions]}


@router.get('/session/{session_id}')
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == user.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')

    messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.id.asc())
        .all()
    )
    return {'data': [MessageResponse.model_validate(message) for message in messages]}


@router.delete('/session/{session_id}')
def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == user.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')

    payload = SessionResponse.model_validate(session)
    db.delete(session)
    db.commit()
    return {'data': payload}


@router.post('/session/{session_id}/chat/stream')
def chat_stream(
    session_id: int,
    payload: MessageCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail='Message content is empty')

    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == user.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')

    agent = (
        db.query(Agent)
        .filter(Agent.id == session.agent_id, Agent.created_by == user.id)
        .first()
    )
    if not agent:
        raise HTTPException(status_code=404, detail='Agent not found')

    # 预先把 ORM 对象需要的字段展开为标量，避免生成器内懒加载失败
    session_title = (session.title or '').strip()
    agent_model = agent.model
    agent_temperature = agent.temperature
    agent_system_prompt = agent.system_prompt

    # 立即在当前依赖 session 内写入 user message 并提交
    user_message = Message(
        session_id=session_id,
        role='user',
        content=content,
    )
    db.add(user_message)
    session.updated_at = now()
    db.commit()
    db.refresh(user_message)
    user_message_id = user_message.id

    # 预取历史消息为标量列表（避免 ORM 对象在 db 关闭后被懒加载）
    history_rows = (
        db.query(Message.role, Message.content)
        .filter(Message.session_id == session_id)
        .order_by(Message.id.asc())
        .all()
    )
    model_messages = []
    if agent_system_prompt:
        model_messages.append({'role': 'system', 'content': agent_system_prompt})
    for role, message_content in history_rows:
        model_messages.append({'role': role, 'content': message_content})

    async def event_generator():
        assistant_parts: list[str] = []
        inner_db = SessionLocal()
        try:
            client = get_llm_client()
            stream = await client.chat.completions.create(
                model=agent_model or get_default_model(),
                messages=model_messages,
                temperature=agent_temperature,
                stream=True,
            )

            yield sse_event(
                'start',
                {
                    'session_id': session_id,
                    'message_id': user_message_id,
                },
            )

            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content or ''
                if not delta:
                    continue
                assistant_parts.append(delta)
                yield sse_event('delta', {'content': delta})

            assistant_text = ''.join(assistant_parts).strip()
            if not assistant_text:
                assistant_text = '抱歉，这次我没有生成有效回复。'

            inner_session = (
                inner_db.query(ChatSession).filter(ChatSession.id == session_id).first()
            )
            assistant_message = Message(
                session_id=session_id,
                role='assistant',
                content=assistant_text,
            )
            inner_db.add(assistant_message)

            if inner_session and (
                    not inner_session.title.strip()
                    or inner_session.title.strip() == DEFAULT_SESSION_TITLE
            ):
                inner_session.title = content[:20] or DEFAULT_SESSION_TITLE

            if inner_session:
                inner_session.updated_at = now()

            inner_db.commit()
            inner_db.refresh(assistant_message)

            yield sse_event(
                'done',
                {
                    'message': MessageResponse.model_validate(assistant_message).model_dump(mode='json')
                },
            )

        except Exception as exc:
            try:
                partial_text = ''.join(assistant_parts).strip()
                if partial_text:
                    inner_session = (
                        inner_db.query(ChatSession).filter(ChatSession.id == session_id).first()
                    )
                    assistant_message = Message(
                        session_id=session_id,
                        role='assistant',
                        content=partial_text,
                    )
                    inner_db.add(assistant_message)

                    if inner_session:
                        inner_session.updated_at = now()

                    inner_db.commit()
            except Exception:
                inner_db.rollback()

            yield sse_event('error', {'message': str(exc)})

        finally:
            try:
                inner_db.close()
            except Exception:
                pass

    return StreamingResponse(
        event_generator(),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
        },
    )