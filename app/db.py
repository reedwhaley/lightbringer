from __future__ import annotations

from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase


class Base(DeclarativeBase):
    pass


engine = None
SessionLocal = None


def init_db(database_url: str) -> None:
    global engine, SessionLocal
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, future=True, connect_args=connect_args)
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
        expire_on_commit=False,
    )


def create_all() -> None:
    if engine is None:
        raise RuntimeError("Database not initialized")
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope():
    if SessionLocal is None:
        raise RuntimeError("Database not initialized")
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()