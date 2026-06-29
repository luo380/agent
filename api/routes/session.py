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
from core.db.models import Agent, ChatSession, Message, User, DEFAULT_SESSION_TITLE, now,Runs,RunSteps
from core.db.session import SessionLocal
from core.service.llm import get_default_model, get_llm_client
from core.service.run_trace import create_run, create_step, complete_step, complete_run, fail_step, fail_run

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


@router.post("/session/{session_id}/chat/stream")
def chat_stream(
    session_id: int,
    payload: MessageCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    这是聊天主入口。

    这段代码现在同时做两件事：
    1. 处理一次正常的聊天请求
    2. 记录这次聊天执行轨迹（Run / RunStep）

    整体流程大致是：
    - 校验输入
    - 校验会话是否存在
    - 校验 Agent 是否存在
    - 创建 Run
    - 按步骤创建 RunStep
    - 调用 LLM 流式返回
    - 保存 assistant 消息
    - 成功则把 Run 标记 completed
    - 失败则把 Run / RunStep 标记 failed
    """
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message content is empty")

    """
    先检查当前 session 是否属于当前用户。

    为什么先查 session：
    - 这条消息一定是发给某个会话的
    - 如果会话不存在，后面所有逻辑都不用继续
    """
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == user.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    """
    再检查当前会话绑定的 Agent 是否存在，并且属于当前用户。

    这里体现了“会话和 Agent 的关系”：
    - 一个 session 绑定一个 agent
    - 聊天执行时，配置来自这个 agent
    """
    agent = (
        db.query(Agent)
        .filter(Agent.id == session.agent_id, Agent.created_by == user.id)
        .first()
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    """
    创建本次执行总记录 Run。

    你可以理解为：
    - 用户每发一条消息
    - 系统就开一张“执行工单”
    - 后面所有步骤都归到这个 run 下面
    """
    run = create_run(
        db,
        session_id=session.id,
        agent_id=agent.id,
        user_id=user.id,
        input_text=content,
    )

    """
    Step 1: 记录“收到用户输入”

    这个步骤的意义：
    - 明确记录这次执行是从哪条输入开始的
    - 如果以后查轨迹，可以看到第一步就是 receive_input
    """
    step_receive = create_step(
        db,
        run_id=run.id,
        step_type="receive_input",
        step_name="接收用户输入",
        input_payload={"content": content},
    )
    complete_step(
        db,
        step_receive,
        output_payload={
            "session_id": session.id,
            "agent_id": agent.id,
        },
    )

    """
    Step 2: 记录“加载 Agent 配置”

    这一步很重要，因为阶段 2 的核心就是：
    聊天运行时依赖 Agent 配置，而不是依赖全局写死配置。
    """
    step_agent = create_step(
        db,
        run_id=run.id,
        step_type="load_agent",
        step_name="加载 Agent 配置",
        input_payload={"agent_id": agent.id},
    )
    complete_step(
        db,
        step_agent,
        output_payload={
            "agent_id": agent.id,
            "agent_name": agent.name,
            "model": agent.model,
            "temperature": agent.temperature,
            "has_system_prompt": bool(agent.system_prompt.strip()),
        },
    )

    """
    先把用户消息落库。

    这和你之前的逻辑一致：
    - 只不过现在在这条链上我们已经有 Run 可以追踪了
    """
    user_message = Message(
        session_id=session_id,
        role="user",
        content=content,
    )
    db.add(user_message)
    session.updated_at = now()
    db.commit()
    db.refresh(user_message)
    user_message_id = user_message.id

    """
    读取历史消息，准备组装给模型的 messages。
    """
    history_rows = (
        db.query(Message.role, Message.content)
        .filter(Message.session_id == session_id)
        .order_by(Message.id.asc())
        .all()
    )

    """
    Step 3: 记录“组装模型输入消息”

    这一步对应的就是：
    - 把 system prompt 加进去
    - 把历史消息整理成 model_messages
    """
    step_build = create_step(
        db,
        run_id=run.id,
        step_type="build_messages",
        step_name="组装模型消息",
        input_payload={"history_count": len(history_rows)},
    )

    model_messages = []
    if agent.system_prompt:
        model_messages.append({"role": "system", "content": agent.system_prompt})

    for role, message_content in history_rows:
        model_messages.append({"role": role, "content": message_content})

    complete_step(
        db,
        step_build,
        output_payload={
            "message_count": len(model_messages),
            "preview_roles": [item["role"] for item in model_messages[:10]],
        },
    )

    # 提前把 ORM 关联的值“脱壳”成纯 Python 值。
    # 因为 event_generator 是一个 async generator：真正执行的时候，
    # 外层的 db session 已经关闭了，run/agent 都是 detached 对象，
    # 再访问 run.id / agent.model 等属性会触发 DetachedInstanceError。
    run_id = run.id
    agent_model = agent.model
    agent_temperature = agent.temperature

    async def event_generator():
        """
        真正的流式输出生成器。

        为什么这里单独用 inner_db：
        - SSE 流式输出可能持续一段时间
        - 主 db 生命周期和生成器内部状态最好分开
        - 这样在流式处理中更新 Run / RunStep 更安全一些
        """
        assistant_parts: list[str] = []
        inner_db = SessionLocal()

        step_llm_id = None
        step_stream_id = None
        step_save_id = None

        try:
            """
            Step 4: 记录“调用 LLM”

            这一步代表：
            - 我们准备向模型发起一次正式调用
            - 这里会记录模型名、温度、消息条数等信息
            """
            step_llm = create_step(
                inner_db,
                run_id=run_id,
                step_type="llm_call",
                step_name="调用 LLM",
                input_payload={
                    "model": agent_model,
                    "temperature": agent_temperature,
                    "message_count": len(model_messages),
                },
            )
            step_llm_id = step_llm.id

            client = get_llm_client()
            stream = await client.chat.completions.create(
                model=agent_model or get_default_model(),
                messages=model_messages,
                temperature=agent_temperature,
                stream=True,
            )

            """
            只要流建立成功，就说明 llm_call 这一步成功了。
            """
            step_llm = inner_db.query(RunSteps).filter(RunSteps.id == step_llm_id).first()
            complete_step(
                inner_db,
                step_llm,
                output_payload={"stream": True},
            )

            """
            Step 5: 记录“接收流式输出”

            这个步骤专门表示：
            - 模型已经开始流式返回内容
            - 我们正在持续接收 delta
            """
            step_stream = create_step(
                inner_db,
                run_id=run_id,
                step_type="stream_response",
                step_name="接收流式响应",
                input_payload={"stream": True},
            )
            step_stream_id = step_stream.id

            """
            给前端发 start 事件。
            顺手把 run_id 也带出去，前端以后就能用这个 run_id 查轨迹。
            """
            yield sse_event(
                "start",
                {
                    "session_id": session_id,
                    "message_id": user_message_id,
                    "run_id": run_id,
                },
            )

            """
            持续消费模型流式输出。
            这里本身不做复杂逻辑，只负责：
            - 拼接 assistant_parts
            - 把 delta 返回给前端
            """
            async for chunk in stream:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta.content or ""
                if not delta:
                    continue

                assistant_parts.append(delta)
                yield sse_event("delta", {"content": delta})

            """
            流结束后，把所有 delta 拼成最终 assistant_text。
            """
            assistant_text = "".join(assistant_parts).strip()
            if not assistant_text:
                assistant_text = "抱歉，这次我没有生成有效回复。"

            """
            stream_response 这一步成功完成。
            """
            step_stream = inner_db.query(RunSteps).filter(RunSteps.id == step_stream_id).first()
            complete_step(
                inner_db,
                step_stream,
                output_payload={
                    "output_length": len(assistant_text),
                    "preview": assistant_text[:200],
                },
            )

            """
            Step 6: 记录“保存 assistant 消息”

            这一步专门记录数据库写入是否成功。
            """
            step_save = create_step(
                inner_db,
                run_id=run_id,
                step_type="save_message",
                step_name="保存助手消息",
                input_payload={"session_id": session_id},
            )
            step_save_id = step_save.id

            inner_session = (
                inner_db.query(ChatSession)
                .filter(ChatSession.id == session_id)
                .first()
            )

            assistant_message = Message(
                session_id=session_id,
                role="assistant",
                content=assistant_text,
            )
            inner_db.add(assistant_message)

            """
            如果当前会话标题还是默认标题，就自动用用户输入前 20 个字做标题。
            这是你原来就有的逻辑。
            """
            if inner_session and (
                not inner_session.title.strip()
                or inner_session.title.strip() == DEFAULT_SESSION_TITLE
            ):
                inner_session.title = content[:20] or DEFAULT_SESSION_TITLE

            if inner_session:
                inner_session.updated_at = now()

            inner_db.commit()
            inner_db.refresh(assistant_message)

            """
            保存 assistant 消息成功，step_save 标记完成。
            """
            step_save = inner_db.query(RunSteps).filter(RunSteps.id == step_save_id).first()
            complete_step(
                inner_db,
                step_save,
                output_payload={
                    "assistant_message_id": assistant_message.id,
                    "output_length": len(assistant_text),
                },
            )

            """
            所有步骤都成功后，整次 Run 标记 completed。
            """
            inner_run = inner_db.query(Runs).filter(Runs.id == run_id).first()
            complete_run(
                inner_db,
                inner_run,
                output_text=assistant_text,
            )

            """
            最后给前端发 done 事件。
            这意味着：
            - assistant 消息已经生成并落库
            - Run 也已经成功结束
            """
            yield sse_event(
                "done",
                {
                    "message": MessageResponse.model_validate(assistant_message).model_dump(mode="json"),
                    "run_id": run_id,
                },
            )

        except Exception as exc:
            """
            这里负责收口错误。

            阶段 3 的重点就在这里：
            - 不是简单 print 一下错误
            - 而是把错误写进 Run / RunStep
            - 以后你就能知道是哪一步失败
            """
            error_text = str(exc)

            try:
                partial_text = "".join(assistant_parts).strip()

                """
                如果 llm_call 还停留在 running，就把它标记 failed。
                """
                if step_llm_id:
                    llm_step = inner_db.query(RunSteps).filter(RunSteps.id == step_llm_id).first()
                    if llm_step and llm_step.status == "running":
                        fail_step(
                            inner_db,
                            llm_step,
                            error_message=error_text,
                        )

                """
                如果 stream_response 还停留在 running，也标记 failed。
                同时保留 partial_text，方便排查“流到一半挂了”的情况。
                """
                if step_stream_id:
                    stream_step = inner_db.query(RunSteps).filter(RunSteps.id == step_stream_id).first()
                    if stream_step and stream_step.status == "running":
                        fail_step(
                            inner_db,
                            stream_step,
                            error_message=error_text,
                            output_payload={"partial_text": partial_text},
                        )

                """
                如果已经拿到部分输出，也可以选择把部分 assistant 内容先保存下来。
                这不是必须，但调试时很有帮助。
                """
                if partial_text:
                    assistant_message = Message(
                        session_id=session_id,
                        role="assistant",
                        content=partial_text,
                    )
                    inner_db.add(assistant_message)
                    inner_db.commit()

                """
                最后把整次 Run 标记 failed。
                这样以后查这次执行详情时，一眼就知道这次执行失败了。
                """
                inner_run = inner_db.query(Runs).filter(Runs.id == run_id).first()
                if inner_run:
                    fail_run(
                        inner_db,
                        inner_run,
                        error_message=error_text,
                        output_text=partial_text,
                    )

            except Exception:
                """
                如果连错误收口都失败了，至少不要把生成器彻底搞崩。
                """
                inner_db.rollback()

            """
            通知前端这次流式执行失败。
            """
            yield sse_event(
                "error",
                {
                    "message": error_text,
                    "run_id": run.id,
                },
            )

        finally:
            """
            无论成功失败，都要关闭 inner_db。
            """
            inner_db.close()

    """
    返回 SSE 流式响应。
    """
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )