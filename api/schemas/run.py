from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RunStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    step_type: str
    step_name: str
    status: str
    input_payload: str
    output_payload: str
    error_message: str
    started_at: datetime
    finished_at: datetime | None
    created_at: datetime


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    agent_id: int
    user_id: int
    status: str
    input_text: str
    output_text: str
    error_message: str
    started_at: datetime
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RunDetailResponse(RunResponse):
    steps: list[RunStepResponse]