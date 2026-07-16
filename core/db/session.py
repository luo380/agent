from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from core.config import settings
from core.db.base import Base

DATABASE_URL = settings.DATABASE_URL
SERVER_URL = settings.DATABASE_SERVER_URL
DB_NAME = settings.DATABASE_NAME

server_engine = create_engine(SERVER_URL, echo=False, future=True)
with server_engine.connect() as conn:
    conn.execute(
        text(
            f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
            "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    )
server_engine.dispose()

engine = create_engine(DATABASE_URL, echo=True, future=True)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
)


def ensure_message_columns() -> None:
    inspector = inspect(engine)
    if "messages" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("messages")}
    alter_statements: list[str] = []

    if "mode" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE messages ADD COLUMN mode VARCHAR(20) NOT NULL DEFAULT 'chat'"
        )
    if "source" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE messages ADD COLUMN source VARCHAR(50) NOT NULL DEFAULT 'chat_stream'"
        )

    if "strict_mode" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE messages ADD COLUMN strict_mode INTEGER NULL"
        )

    if not alter_statements:
        return

    with engine.begin() as conn:
        for statement in alter_statements:
            conn.execute(text(statement))


def init_db() -> None:
    import core.db.models

    Base.metadata.create_all(bind=engine)
    ensure_message_columns()


if __name__ == "__main__":
    init_db()
