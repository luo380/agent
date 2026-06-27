from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    system_prompt: str = Field(default='', max_length=20000)
    welcome_message: str = Field(default='', max_length=2000)
    model: str = Field(default='qwen/qwen3-1.7b', min_length=1, max_length=120)
    temperature: float = Field(default=0.2, ge=0, le=2)


class AgentUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    system_prompt: str = Field(default='', max_length=20000)
    welcome_message: str = Field(default='', max_length=2000)
    model: str = Field(min_length=1, max_length=120)
    temperature: float = Field(ge=0, le=2)


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    system_prompt: str
    welcome_message: str
    model: str
    temperature: float
    created_by: int
    created_at: datetime
    updated_at: datetime

    @field_validator('welcome_message', mode='before')
    @classmethod
    def normalize_welcome_message(cls, value):
        return '' if value is None else value
