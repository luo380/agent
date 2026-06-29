from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base

LongText = Text().with_variant(LONGTEXT(), 'mysql')
DEFAULT_SESSION_TITLE = '新对话'
RUN_STATUS_RUNNING = "running"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_FAILED = "failed"

STEP_STATUS_RUNNING = "running"
STEP_STATUS_COMPLETED = "completed"
STEP_STATUS_FAILED = "failed"


def now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class Agent(Base):
    __tablename__ = 'agents'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, default='', nullable=False)
    welcome_message: Mapped[str] = mapped_column(Text, default='', nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.4, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class ChatSession(Base):
    __tablename__ = 'sessions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default=DEFAULT_SESSION_TITLE, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    agent_id: Mapped[int] = mapped_column(ForeignKey('agents.id', ondelete='CASCADE'), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class Message(Base):
    __tablename__ = 'messages'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('sessions.id', ondelete='CASCADE'), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)

class Runs(Base):
    __tablename__ = 'runs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('sessions.id', ondelete='CASCADE'), index=True, nullable=False)
    agent_id: Mapped[int] = mapped_column(ForeignKey('agents.id', ondelete='CASCADE'), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    output_text: Mapped[str] = mapped_column(Text, default='', nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default='', nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)


class RunSteps(Base):
    __tablename__ = 'run_steps'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('runs.id', ondelete='CASCADE'), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    step_type: Mapped[str] = mapped_column(String(20), nullable=False)
    step_name: Mapped[str] = mapped_column(String(20), nullable=False)
    input_payload: Mapped[str] = mapped_column(Text, nullable=False)
    output_payload: Mapped[str] = mapped_column(Text, default='', nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default='', nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)