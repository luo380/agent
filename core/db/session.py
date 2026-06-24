from sqlalchemy import create_engine, text
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


def init_db() -> None:
    import core.db.models
    Base.metadata.create_all(bind=engine)


    
if __name__ == "__main__":
    init_db()