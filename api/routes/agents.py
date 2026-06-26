from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.schemas.agent import AgentCreateRequest, AgentResponse, AgentUpdateRequest
from core.db.models import Agent, User, ChatSession

router = APIRouter()


@router.post('/create_agent')
def create_agent(
    payload: AgentCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = Agent(
        name=payload.name.strip(),
        system_prompt=payload.system_prompt.strip(),
        welcome_message=payload.welcome_message.strip(),
        model=payload.model.strip(),
        temperature=payload.temperature,
        created_by=user.id,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return {'data': AgentResponse.model_validate(agent)}


@router.get('/list_agents')
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
    return {'data': [AgentResponse.model_validate(agent) for agent in agents]}


@router.put('/agent/{agent_id}')
def update_agent(
    agent_id: int,
    payload: AgentUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = (
        db.query(Agent)
        .filter(Agent.id == agent_id, Agent.created_by == user.id)
        .first()
    )
    if not agent:
        raise HTTPException(status_code=404, detail='Agent not found')

    agent.name = payload.name.strip()
    agent.system_prompt = payload.system_prompt.strip()
    agent.welcome_message = payload.welcome_message.strip()
    agent.model = payload.model.strip()
    agent.temperature = payload.temperature


    db.commit()
    db.refresh(agent)
    return {'data': AgentResponse.model_validate(agent)}


@router.delete('/agent/{agent_id}')
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
        raise HTTPException(status_code=404, detail='Agent not found')

  
    related_session = (
        db.query(ChatSession)
        .filter(ChatSession.agent_id == agent.id, ChatSession.user_id == user.id)
        .first()
    )
    if related_session:
        raise HTTPException(status_code=400, detail="Agent has related sessions")
    deleted = AgentResponse.model_validate(agent)
    db.delete(agent)
    db.commit()
    return {
        'message': '删除成功',
        'data': deleted,
    }
