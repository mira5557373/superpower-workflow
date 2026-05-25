from __future__ import annotations

from sqlalchemy import Engine
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_engine_from_url(
    url: str,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
) -> Engine:
    kwargs: dict = {}
    if not url.startswith("sqlite"):
        kwargs.update(pool_size=pool_size, max_overflow=max_overflow, pool_timeout=pool_timeout)
    return sa_create_engine(url, **kwargs)


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
