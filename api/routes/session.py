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


# =============================================================================
# POST /session/{session_id}/chat/stream —— 聊天主入口（SSE 流式输出）
# -----------------------------------------------------------------------------
# 【功能概述】
#   客户端向指定 session 发送一条消息，服务端：
#     1. 校验会话 & Agent 合法性
#     2. 创建一次 Run（执行工单）和多个 RunStep（执行步骤）
#     3. 调用 LLM 以 SSE 流式方式返回内容
#     4. 将 assistant 消息落库保存
#     5. 完成后把 Run 标记为 completed，出错则标记 failed
#
# 【返回格式】Server-Sent Events (SSE)
#   事件类型有三种：
#     - "start" : 流即将开始，附带 run_id / message_id，供前端查轨迹用
#     - "delta" : LLM 的增量输出（一段一段的文本）
#     - "done"  : 流结束，附带完整的 assistant message 对象
#     - "error" : 流执行失败，附带错误信息
# =============================================================================
@router.post("/session/{session_id}/chat/stream")
def chat_stream(
    # URL 路径参数：本次消息发送到哪个会话
    session_id: int,
    # 请求体：Pydantic Schema 校验，包含用户消息内容
    payload: MessageCreateRequest,
    # 依赖注入：数据库会话（注意：主函数用的是外层 db，流内部用 inner_db）
    db: Session = Depends(get_db),
    # 依赖注入：当前登录用户（未登录自动 401）
    user: User = Depends(get_current_user),
):
    # -------------------------------------------------------------------------
    # 一、输入校验：消息非空
    # -------------------------------------------------------------------------
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message content is empty")

    # -------------------------------------------------------------------------
    # 二、校验会话是否存在且属于当前用户
    #   先查 session 的原因：
    #     - 每条消息必然归属某个会话
    #     - 若会话不存在 / 不属于当前用户，后续逻辑无需继续
    # -------------------------------------------------------------------------
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == user.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # -------------------------------------------------------------------------
    # 三、校验会话绑定的 Agent 是否存在且属于当前用户
    #   这里体现了「Session → Agent」的归属关系：
    #     - 一个 session 绑定一个 agent
    #     - LLM 调用时的模型、温度、system_prompt 等配置均来自该 agent
    # -------------------------------------------------------------------------
    agent = (
        db.query(Agent)
        .filter(Agent.id == session.agent_id, Agent.created_by == user.id)
        .first()
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # -------------------------------------------------------------------------
    # 四、创建 Run（本次执行的总记录）
    #   用户每发一条消息 → 系统开一张「执行工单」
    #   后续所有 RunStep 都会挂在这个 run.id 下，便于整体追溯
    # -------------------------------------------------------------------------
    run = create_run(
        db,
        session_id=session.id,
        agent_id=agent.id,
        user_id=user.id,
        input_text=content,
    )

    # =========================================================================
    # Step 1: 记录「收到用户输入」
    # -------------------------------------------------------------------------
    # 目的：明确这次执行的起点。后续回溯时能一眼看到第一条输入内容是什么
    # =========================================================================
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

    # =========================================================================
    # Step 2: 记录「加载 Agent 配置」
    # -------------------------------------------------------------------------
    # 重要性：聊天运行时的模型、温度、system_prompt 完全由 Agent 配置决定，
    #         而非全局写死。记录此步骤便于排查「模型对不上」等问题。
    # =========================================================================
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
            "agent_name": agent.name,                 # Agent 名称
            "model": agent.model,                     # 使用的 LLM 模型名
            "temperature": agent.temperature,         # 采样温度
            "has_system_prompt": bool(agent.system_prompt.strip()),  # 是否有自定义系统提示
        },
    )

    # -------------------------------------------------------------------------
    # 五、保存用户消息到数据库
    #   - 先把 user 消息落库，再去调模型
    #   - 同时更新 session.updated_at，让列表接口能按最近活动排序
    # -------------------------------------------------------------------------
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

    # -------------------------------------------------------------------------
    # 六、读取历史消息（本次会话内所有消息，按时间升序）
    #   用于组装给 LLM 的 messages 列表，让模型具备上下文记忆
    # -------------------------------------------------------------------------
    history_rows = (
        db.query(Message.role, Message.content)
        .filter(Message.session_id == session_id)
        .order_by(Message.id.asc())
        .all()
    )

    # =========================================================================
    # Step 3: 记录「组装模型输入消息」
    # -------------------------------------------------------------------------
    # 逻辑：
    #   - 如果 Agent 有 system_prompt，作为第一条 system 消息
    #   - 按顺序追加历史消息（user / assistant 交替）
    # =========================================================================
    step_build = create_step(
        db,
        run_id=run.id,
        step_type="build_messages",
        step_name="组装模型消息",
        input_payload={"history_count": len(history_rows)},
    )

    # 最终发给模型的消息列表（标准 OpenAI 格式：[{"role": "...", "content": "..."}]）
    model_messages = []

    # 3.1 追加系统提示（若 Agent 配置了 system_prompt）
    if agent.system_prompt:
        model_messages.append({"role": "system", "content": agent.system_prompt})

    # 3.2 按顺序追加历史消息（role 可能是 "user" 或 "assistant"）
    for role, message_content in history_rows:
        model_messages.append({"role": role, "content": message_content})

    complete_step(
        db,
        step_build,
        output_payload={
            "message_count": len(model_messages),
            # 预览前 10 条消息的 role，便于调试（太长不输出完整内容，避免泄露/体积过大）
            "preview_roles": [item["role"] for item in model_messages[:10]],
        },
    )

    # -------------------------------------------------------------------------
    # 七、"脱壳"：提前把 ORM 对象的关键属性取成纯 Python 值
    #   【原因】event_generator 是一个异步生成器。
    #   当外层函数返回 StreamingResponse 后，外层的 db 会话已关闭、
    #   run/agent 这些 ORM 对象已处于 detached 状态。
    #   此时若在生成器内访问 run.id / agent.model 会触发 DetachedInstanceError。
    #   解决方案：在生成器外部先把需要用到的值"脱壳"保存为普通变量。
    # -------------------------------------------------------------------------
    run_id = run.id
    agent_model = agent.model
    agent_temperature = agent.temperature

    # =========================================================================
    # 异步生成器：真正的流式输出逻辑（执行在 db 已关闭之后）
    # -------------------------------------------------------------------------
    # 【设计要点】
    #   - 内部使用 inner_db（新建 SessionLocal）管理自身的数据库操作，
    #     避免与外层已关闭的 db 会话冲突
    #   - 所有对 Run / RunStep 的状态更新都通过 inner_db 完成
    #   - 以 yield 方式逐段返回 SSE 事件
    # =========================================================================
    async def event_generator():

        # 存储 LLM 增量输出的每一段文本（最后 join 成完整回答）
        assistant_parts: list[str] = []

        # 内部数据库会话，生命周期 = 本次流式输出过程
        inner_db = SessionLocal()

        # 预先声明三个可能在异常时需要兜底的 step_id
        step_llm_id = None      # Step 4: 调用 LLM
        step_stream_id = None   # Step 5: 接收流式输出
        step_save_id = None     # Step 6: 保存 assistant 消息

        try:
            # =================================================================
            # Step 4: 记录「调用 LLM」
            # -----------------------------------------------------------------
            # 记录模型名称、温度、消息条数等信息，便于排查"模型配置不对"等问题
            # =================================================================
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

            # -----------------------------------------------------------------
            # 4.1 发起 LLM 流式调用（stream=True）
            #   - model: Agent 配置的模型名，为空则回退到系统默认模型
            #   - temperature: Agent 配置的采样温度
            #   - messages: 前面组装好的消息列表（含 system prompt 与历史消息）
            #   - stream=True: 开启流式返回，服务器会边生成边回传
            # -----------------------------------------------------------------
            client = get_llm_client()
            stream = await client.chat.completions.create(
                model=agent_model or get_default_model(),
                messages=model_messages,
                temperature=agent_temperature,
                stream=True,
            )

            # -----------------------------------------------------------------
            # 4.2 只要成功建立流式连接，就把「调用 LLM」这一步标记 completed
            #     （注意：这一步只代表"成功发起请求"，内容还在持续返回中）
            # -----------------------------------------------------------------
            step_llm = inner_db.query(RunSteps).filter(RunSteps.id == step_llm_id).first()
            complete_step(
                inner_db,
                step_llm,
                output_payload={"stream": True},
            )

            # =================================================================
            # Step 5: 记录「接收流式响应」
            # -----------------------------------------------------------------
            # 表示 LLM 已开始流式输出，本 step 追踪整个流消费过程
            # =================================================================
            step_stream = create_step(
                inner_db,
                run_id=run_id,
                step_type="stream_response",
                step_name="接收流式响应",
                input_payload={"stream": True},
            )
            step_stream_id = step_stream.id

            # -----------------------------------------------------------------
            # 5.1 向客户端发送 "start" 事件（流即将开始的信号）
            #     顺便把 run_id 带出，前端即可用这个 ID 去查执行轨迹
            # -----------------------------------------------------------------
            yield sse_event(
                "start",
                {
                    "session_id": session_id,
                    "message_id": user_message_id,
                    "run_id": run_id,
                },
            )

            # -----------------------------------------------------------------
            # 5.2 逐块消费模型的流式输出
            #     处理逻辑：
            #       - 跳过空 choices（部分服务端心跳/控制帧无内容）
            #       - 从 delta 中取出增量文本 content
            #       - 追加到 assistant_parts（用于最后拼出完整文本）
            #       - 同时 yield "delta" 事件推给前端（实现打字机效果）
            # -----------------------------------------------------------------
            async for chunk in stream:
                # 某些 chunk 可能不包含 choices（如 [DONE] 标记或控制帧），直接跳过
                if not chunk.choices:
                    continue

                # 取第一条 choice 的增量内容（流式场景下 choices 通常只有 1 项）
                delta = chunk.choices[0].delta.content or ""
                # 空字符串也跳过，避免前端收到空片段
                if not delta:
                    continue

                assistant_parts.append(delta)
                yield sse_event("delta", {"content": delta})

            # -----------------------------------------------------------------
            # 5.3 流消费完成：拼接出完整 assistant_text
            #     某些边缘情况（例如模型拒绝回答）可能所有 delta 全为空，
            #     此时用固定兜底文本代替，避免前端收到一条空白回答
            # -----------------------------------------------------------------
            assistant_text = "".join(assistant_parts).strip()
            if not assistant_text:
                assistant_text = "抱歉，这次我没有生成有效回复。"

            # -----------------------------------------------------------------
            # 5.4 「接收流式响应」这一步标记 completed
            #     记录：最终输出长度、前 200 字预览
            # -----------------------------------------------------------------
            step_stream = inner_db.query(RunSteps).filter(RunSteps.id == step_stream_id).first()
            complete_step(
                inner_db,
                step_stream,
                output_payload={
                    "output_length": len(assistant_text),
                    "preview": assistant_text[:200],
                },
            )

            # =================================================================
            # Step 6: 记录「保存 assistant 消息」
            # -----------------------------------------------------------------
            # 专门为数据库写入开一个 step，便于定位"是否落库失败"
            # =================================================================
            step_save = create_step(
                inner_db,
                run_id=run_id,
                step_type="save_message",
                step_name="保存助手消息",
                input_payload={"session_id": session_id},
            )
            step_save_id = step_save.id

            # 6.1 查询 session（inner_db 视角下需重新查询才能绑定到 inner_db）
            inner_session = (
                inner_db.query(ChatSession)
                .filter(ChatSession.id == session_id)
                .first()
            )

            # 6.2 构造 assistant 消息并添加到数据库
            assistant_message = Message(
                session_id=session_id,
                role="assistant",
                content=assistant_text,
            )
            inner_db.add(assistant_message)

            # 6.3 自动标题逻辑：若当前会话仍为默认标题，用用户消息前 20 字作为新标题
            #     保留原有的 UX 小优化：用户首次聊天后，会话自动拥有一个可读标题
            if inner_session and (
                not inner_session.title.strip()
                or inner_session.title.strip() == DEFAULT_SESSION_TITLE
            ):
                inner_session.title = content[:20] or DEFAULT_SESSION_TITLE

            # 6.4 无论是否更新标题，刷新会话最后活动时间
            if inner_session:
                inner_session.updated_at = now()

            inner_db.commit()
            inner_db.refresh(assistant_message)

            # 6.5 「保存助手消息」这一步标记 completed
            step_save = inner_db.query(RunSteps).filter(RunSteps.id == step_save_id).first()
            complete_step(
                inner_db,
                step_save,
                output_payload={
                    "assistant_message_id": assistant_message.id,
                    "output_length": len(assistant_text),
                },
            )

            # -----------------------------------------------------------------
            # 八、所有子步骤成功 → 整次 Run 标记 completed，并保存最终输出
            # -----------------------------------------------------------------
            inner_run = inner_db.query(Runs).filter(Runs.id == run_id).first()
            complete_run(
                inner_db,
                inner_run,
                output_text=assistant_text,
            )

            # -----------------------------------------------------------------
            # 九、向客户端发送 "done" 事件（流结束信号）
            #     把完整的 assistant message 对象带出，供前端直接展示或落库
            # -----------------------------------------------------------------
            yield sse_event(
                "done",
                {
                    "message": MessageResponse.model_validate(assistant_message).model_dump(mode="json"),
                    "run_id": run_id,
                },
            )

        # =====================================================================
        # 异常处理：流式过程中任意环节出错均进入这里
        # ---------------------------------------------------------------------
        # 【关键设计】不是简单 print 错误，而是把错误写进 Run / RunStep，
        #            这样将来查执行详情时能一眼看到"哪一步失败、错误是什么"
        # =====================================================================
        except Exception as exc:
            error_text = str(exc)

            try:
                # 先把已收到的部分文本拼出来（即使失败也保留断点排查信息）
                partial_text = "".join(assistant_parts).strip()

                # --- 兜底 1：若「调用 LLM」仍在 running，标记 failed ---
                if step_llm_id:
                    llm_step = inner_db.query(RunSteps).filter(RunSteps.id == step_llm_id).first()
                    if llm_step and llm_step.status == "running":
                        fail_step(
                            inner_db,
                            llm_step,
                            error_message=error_text,
                        )

                # --- 兜底 2：若「接收流式响应」仍在 running，标记 failed ---
                #            同时把 partial_text 存进 output_payload，便于排查"流到一半挂了"
                if step_stream_id:
                    stream_step = inner_db.query(RunSteps).filter(RunSteps.id == step_stream_id).first()
                    if stream_step and stream_step.status == "running":
                        fail_step(
                            inner_db,
                            stream_step,
                            error_message=error_text,
                            output_payload={"partial_text": partial_text},
                        )

                # --- 兜底 3：若已有部分输出，也可以先保存到数据库（非必须，便于调试）---
                if partial_text:
                    assistant_message = Message(
                        session_id=session_id,
                        role="assistant",
                        content=partial_text,
                    )
                    inner_db.add(assistant_message)
                    inner_db.commit()

                # --- 兜底 4：整次 Run 标记 failed ---
                inner_run = inner_db.query(Runs).filter(Runs.id == run_id).first()
                if inner_run:
                    fail_run(
                        inner_db,
                        inner_run,
                        error_message=error_text,
                        output_text=partial_text,
                    )
            except Exception:
                # 若"错误收口本身也失败"（例如数据库事务异常），至少回滚事务，不让生成器彻底崩溃
                inner_db.rollback()

            # 向客户端发送 "error" 事件，通知前端本次执行失败
            yield sse_event(
                "error",
                {
                    "message": error_text,
                    "run_id": run_id,
                },
            )

        # =====================================================================
        # finally 块：无论成功失败，确保 inner_db 会话被关闭，避免连接泄漏
        # =====================================================================
        finally:
            inner_db.close()

    # -------------------------------------------------------------------------
    # 返回 SSE 流式响应
    #   - media_type="text/event-stream" : 浏览器/客户端据此识别为 SSE
    #   - 注意：FastAPI 普通 def 函数内返回 async generator 需要配合合适的
    #     StreamingResponse，这里依赖 uvicorn 对 async generator 的支持
    # -------------------------------------------------------------------------
    return StreamingResponse(event_generator(), media_type="text/event-stream")