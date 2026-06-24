from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.deps import get_db, get_current_user
from api.schemas.agent import AgentCreateRequest, AgentResponse
from core.db.models import User, Agent, ChatSession

router = APIRouter()

# 创建智能体
@router.post("/create_agent")
def create_agent( payload: AgentCreateRequest,
                 db: Session = Depends(get_db),
         user: User = Depends(get_current_user),
):
    agent = Agent(
        name=payload.name,
        system_prompt=payload.system_prompt,
        model=payload.model,
        temperature=payload.temperature,
        created_by=user.id,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return {
        "data": AgentResponse.model_validate(agent)
    }

# 获取智能体列表
@router.get("/list_agents")
def list_agents(
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
):
    agents = (
        db.query(Agent)
        .filter(Agent.created_by == user.id)
        .order_by(Agent.id.desc())
        .all()
    )
    return {
        "data": [AgentResponse.model_validate(agent) for agent in agents]
    }

# 删除智能体
@router.post("/agent/{agent_id}")
def delete_agent(
        agent_id: int,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
):
    agent = (
        db.query(Agent)
        .filter(Agent.id == agent_id, Agent.created_by == user.id)
        .first()
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # 删除智能体的所有会话
    session = db.query(ChatSession).filter(ChatSession.agent_id == agent_id).delete()
    if  session:
        raise HTTPException(status_code=400, detail="当前智能体下存在会话，不能删除。")

    db.delete(agent)
    db.commit()
    return {
        "message": "删除成功"
    }

# 更新智能体
@router.post("/agent/{agent_id}")
def update_agent(
        agent_id: int,
        payload: AgentCreateRequest,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
):
    agent = (
        db.query(Agent)
        .filter(Agent.id == agent_id, Agent.created_by == user.id)
        .first()
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent.name = payload.name
    agent.system_prompt = payload.system_prompt
    agent.model = payload.model
    agent.temperature = payload.temperature
    db.commit()
    db.refresh(agent)
    return {
        "data": AgentResponse.model_validate(agent)
    }
