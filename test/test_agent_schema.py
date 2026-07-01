from datetime import datetime
from types import SimpleNamespace

from api.schemas.agent import AgentResponse


def test_agent_response_coerces_null_welcome_message():
    agent = SimpleNamespace(
        id=1,
        name='Test Agent',
        system_prompt='You are helpful.',
        welcome_message=None,
        model='qwen/qwen3-1.7b',
        temperature=0.2,
        created_by=1,
        created_at=datetime(2026, 6, 26, 0, 0, 0),
        updated_at=datetime(2026, 6, 26, 0, 0, 0),
    )

    result = AgentResponse.model_validate(agent)

    assert result.welcome_message == ''
