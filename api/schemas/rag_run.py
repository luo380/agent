from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RagRunStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rag_run_id: int
    status: str
    step_type: str
    step_name: str
    input_payload: str
    output_payload: str
    error_message: str
    started_at: datetime
    finished_at: datetime | None
    created_at: datetime


class RagRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    question: str
    answer: str
    status: str
    document_scope_json: str
    strict_mode: int
    top_k: int
    error_message: str
    started_at: datetime
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RagRunDetailResponse(RagRunResponse):
    steps: list[RagRunStepResponse]