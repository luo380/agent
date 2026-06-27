import json


from sqlalchemy.orm import Session

from core.db.models import RUN_STATUS_RUNNING, now, RUN_STATUS_COMPLETED, RUN_STATUS_FAILED, STEP_STATUS_FAILED, \
    STEP_STATUS_COMPLETED, STEP_STATUS_RUNNING,Runs,RunSteps


def dump_payload(payload: dict | list | None) -> str:
    """
    把 Python 的 dict / list 转成 JSON 字符串，方便存进数据库。

    为什么需要这个函数：
    - RunStep 里我们通常会存 input_payload / output_payload
    - 数据库存的是 Text，不是 Python 对象
    - 所以这里统一做一次 JSON 序列化

    参数:
    - payload: 要保存的结构化数据，可以是 dict、list，也可以是 None

    返回:
    - JSON 字符串；如果是 None，就返回空字符串
    """
    if payload is None:
        return ""
    return json.dumps(payload, ensure_ascii=False)



def create_run(
    db: Session,
    *,
    session_id: int,
    agent_id: int,
    user_id: int,
    input_text: str,
) -> Runs:
    """
    创建一次“消息执行记录”。

    你可以把 Run 理解成：
    - 用户发一条消息
    - 系统为这条消息创建一张“执行总单”
    - 后面所有步骤都挂在这张总单下面

    适用时机:
    - 在 chat_stream() 一开始，校验完 session / agent 之后立刻创建

    参数:
    - db: 当前数据库会话
    - session_id: 当前消息所属会话
    - agent_id: 当前会话绑定的 Agent
    - user_id: 当前登录用户
    - input_text: 用户本次输入内容

    返回:
    - 新创建好的 Run ORM 对象
    """
    run = Runs(
        session_id=session_id,
        agent_id=agent_id,
        user_id=user_id,
        status=RUN_STATUS_RUNNING,
        input_text=input_text,
        started_at=now(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run



def complete_run(
    db: Session,
    run: Runs,
    *,
    output_text: str,
) -> Runs:
    """
    把一次执行标记为“成功完成”。

    适用时机:
    - 模型流式输出结束
    - assistant 消息成功写入数据库
    - 整条消息链路没有报错

    会做的事:
    - status 改成 completed
    - 保存最终输出 output_text
    - 清空 error_message
    - 写 finished_at

    参数:
    - db: 当前数据库会话
    - run: 要更新的 Run 对象
    - output_text: 本次最终生成的回复内容

    返回:
    - 更新后的 Run ORM 对象
    """
    run.status = RUN_STATUS_COMPLETED
    run.output_text = output_text
    run.error_message = ""
    run.finished_at = now()
    db.commit()
    db.refresh(run)
    return run

def fail_run(
    db: Session,
    run: Runs,
    *,
    error_message: str,
    output_text: str = "",
) -> Runs:
    """
    把一次执行标记为“失败”。

    适用时机:
    - 调模型报错
    - 存消息报错
    - 任一步骤异常导致整条链路没有完整结束

    会做的事:
    - status 改成 failed
    - 保存错误信息
    - 如果有部分输出，可以顺手存到 output_text
    - 写 finished_at

    参数:
    - db: 当前数据库会话
    - run: 要更新的 Run 对象
    - error_message: 失败原因
    - output_text: 可选，部分输出内容，比如流式输出到一半时拿到的文本

    返回:
    - 更新后的 Run ORM 对象
    """
    run.status = RUN_STATUS_FAILED
    run.error_message = error_message
    run.output_text = output_text
    run.finished_at = now()
    db.commit()
    db.refresh(run)
    return run


def create_step(
    db: Session,
    *,
    run_id: int,
    step_type: str,
    step_name: str,
    input_payload: dict | list | None = None,
) -> RunSteps:
    """
    创建某一个执行步骤。

    你可以把 RunStep 理解成：
    - Run 是“总流程”
    - RunStep 是“流程中的某一步”

    例如:
    - receive_input
    - load_agent
    - build_messages
    - llm_call
    - stream_response
    - save_message

    适用时机:
    - 每进入一个关键步骤前，先创建一个 RunStep
    - 默认状态先记为 running

    参数:
    - db: 当前数据库会话
    - run_id: 这一步属于哪个 Run
    - step_type: 步骤类型，建议用于程序判断，如 "llm_call"
    - step_name: 步骤名称，建议用于展示，如 "调用 LLM"
    - input_payload: 该步骤的输入数据摘要

    返回:
    - 新创建好的 RunStep ORM 对象
    """
    step = RunSteps(
        run_id=run_id,
        step_type=step_type,
        step_name=step_name,
        status=STEP_STATUS_RUNNING,
        input_payload=dump_payload(input_payload),
        started_at=now(),
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def complete_step(
    db: Session,
    step: RunSteps,
    *,
    output_payload: dict | list | None = None,
) -> RunSteps:
    """
    把某一步标记为“成功完成”。

    适用时机:
    - 例如 Agent 成功加载完
    - prompt 成功组装完
    - LLM 调用成功建立流
    - assistant 消息成功保存

    会做的事:
    - status 改成 completed
    - 保存该步骤输出摘要
    - 清空 error_message
    - 写 finished_at

    参数:
    - db: 当前数据库会话
    - step: 要更新的 RunStep 对象
    - output_payload: 该步骤输出的数据摘要

    返回:
    - 更新后的 RunStep ORM 对象
    """
    step.status = STEP_STATUS_COMPLETED
    step.output_payload = dump_payload(output_payload)
    step.error_message = ""
    step.finished_at = now()
    db.commit()
    db.refresh(step)
    return step


def fail_step(
    db: Session,
    step: RunSteps,
    *,
    error_message: str,
    output_payload: dict | list | None = None,
) -> RunSteps:
    """
    把某一步标记为“失败”。

    适用时机:
    - 调模型时报错
    - 解析流式结果时报错
    - 保存 assistant 消息时报错

    会做的事:
    - status 改成 failed
    - 保存错误信息
    - 如果有部分输出，也一并保存
    - 写 finished_at

    参数:
    - db: 当前数据库会话
    - step: 要更新的 RunStep 对象
    - error_message: 失败原因
    - output_payload: 可选，这一步即使失败也可能有部分结果

    返回:
    - 更新后的 RunStep ORM 对象
    """
    step.status = STEP_STATUS_FAILED
    step.output_payload = dump_payload(output_payload)
    step.error_message = error_message
    step.finished_at = now()
    db.commit()
    db.refresh(step)
    return step

