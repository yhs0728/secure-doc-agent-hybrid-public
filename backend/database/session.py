from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from config.settings import get_settings


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when database access is requested while PostgreSQL is disabled."""


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    if not settings.database_enabled or settings.database_url is None:
        raise DatabaseNotConfiguredError(
            "PostgreSQL이 비활성화되어 있습니다. DATABASE_ENABLED=true와 "
            "DATABASE_URL을 설정하세요."
        )

    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        pool_recycle=settings.database_pool_recycle_seconds,
        pool_use_lifo=settings.database_pool_use_lifo,
        connect_args={
            "options": f"-c statement_timeout={settings.database_statement_timeout_ms}",
        },
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(),
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


def get_database_session() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def transaction() -> Generator[Session, None, None]:
    with get_session_factory()() as session, session.begin():
        yield session


def set_local_user_context(session: Session, user_id: UUID) -> None:
    """Set the RLS identity for the current transaction only."""
    session.execute(
        text("SELECT set_config('app.user_id', :user_id, true)"),
        {"user_id": str(user_id)},
    )


def check_database_connection() -> bool:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except (DatabaseNotConfiguredError, OSError, SQLAlchemyError):
        return False


def reset_database_caches() -> None:
    get_session_factory.cache_clear()
    engine = get_engine.cache_info()
    if engine.currsize:
        try:
            get_engine().dispose()
        except DatabaseNotConfiguredError:
            pass
    get_engine.cache_clear()
