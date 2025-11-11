from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base, Session

from common.config import settings


def _build_dsn() -> str:
    if settings.POSTGRES_DSN:
        return settings.POSTGRES_DSN
    # запасной путь — сборка из кусочков
    return (
        f"postgresql+psycopg2://{settings.DB_USER}:{settings.DB_PASSWORD}"
        f"@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
    )


engine = create_engine(_build_dsn(), pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def wait_for_db(timeout_sec: int = 60) -> None:
    started = time.time()
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception:
            if time.time() - started > timeout_sec:
                raise
            time.sleep(1)


def get_db() -> Generator[Session, None, None]:
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
