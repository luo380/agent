from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.db.base import Base
from core.db.models import Agent, ChatSession, User


@pytest.fixture
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )

    Base.metadata.create_all(bind=engine)
    db = testing_session_local()

    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def seeded_chat_context(db_session):
    user = User(
        email="stage3@example.com",
        name="Stage 3 User",
        password_hash="not-used-in-these-tests",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    agent = Agent(
        name="Trace Agent",
        system_prompt="You are a trace-aware assistant.",
        welcome_message="hello",
        model="qwen/qwen3-1.7b",
        temperature=0.2,
        created_by=user.id,
    )
    db_session.add(agent)
    db_session.commit()
    db_session.refresh(agent)

    session = ChatSession(
        title="Stage 3 Session",
        user_id=user.id,
        agent_id=agent.id,
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    return SimpleNamespace(
        user=user,
        agent=agent,
        session=session,
    )
