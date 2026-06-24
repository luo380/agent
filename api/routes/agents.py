from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import get_db, get_current_user
from api.schemas.agent import AgentCreateRequest, AgentResponse
from core.db.models import User, Agent

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
