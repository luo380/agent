from openai import AsyncOpenAI

from core.config import settings

def get_llm_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY,
                       base_url=settings.OPENAI_BASE_URL,
                       )

def get_default_model() -> str:
    return settings.LLM_MODEL

def get_default_temperature() -> float:
    return settings.LLM_TEMPERATURE