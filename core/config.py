from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "http://localhost:1234/v1")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "lm-studio")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "qwen/qwen3-1.7b")
    EMBEDDING_MODEL: str = os.getenv(
        "EMBEDDING_MODEL",
        "text-embedding-nomic-embed-text-v1.5",
    )
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0"))

    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-to-a-long-random-string")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")
    )

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://root:root@127.0.0.1:3306/agent_v1",
    )
    DATABASE_SERVER_URL: str = os.getenv(
        "DATABASE_SERVER_URL",
        "mysql+pymysql://root:root@127.0.0.1:3306",
    )
    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "agent_v1")


settings = Settings()