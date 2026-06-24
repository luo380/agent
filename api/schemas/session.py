from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from core.db.models import DEFAULT_SESSION_TITLE


class SessionCreateRequest(BaseModel):
    agent_id: int
    title: str = Field(default=DEFAULT_SESSION_TITLE, min_length=1, max_length=200)


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    user_id: int
    agent_id: int
    created_at: datetime
    updated_at: datetime


class MessageCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20000)


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    role: str
    content: str
    created_at: datetime