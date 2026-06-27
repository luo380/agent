from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.deps import get_db, get_current_user
from api.schemas.run import RunResponse, RunDetailResponse, RunStepResponse
from core.db.models import User, ChatSession, Runs, RunSteps

router = APIRouter()


# 通过会话id获取会话历史轨迹
@router.get("/session/{session_id}")
def get_session_history(session_id: str,
                        db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):

    session = (
        db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.user_id == user.id)
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')

    runs = (
        db.query(Runs).filter(Runs.session_id == session.id)
    ).order_by(Runs.id.desc()).first()

    if not runs:
        raise HTTPException(status_code=404, detail='No history found')

    return {'data': RunResponse.model_validate(runs)}


# 获取轨迹详情
@router.get("/run/{run_id}")
def get_run_detail(run_id: str,
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):

    run = db.query(Runs).filter(Runs.id == run_id, Runs.user_id == user.id).first()

    if not run:
        raise HTTPException(status_code=404, detail='Run not found')

    steps = db.query(RunSteps).filter(RunSteps.run_id == run.id).all()
    if not steps:
        raise HTTPException(status_code=404, detail='No steps found')

    data = RunDetailResponse(
        **RunResponse.model_validate(run).model_dump(),
        steps=[RunStepResponse.model_validate(step) for step in steps],
    )

    return {'data': data}

