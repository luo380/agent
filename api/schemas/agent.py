from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict

class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    system_prompt: str = Field(default="", max_length=20000)
    model: str = Field(default="qwen/qwen3-1.7b", min_length=1, max_length=120)
    temperature: float = Field(default=0, ge=0, le=2)


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    system_prompt: str
    model: str
    temperature: float
    created_by: int
    created_at: datetime
    updated_at: datetime