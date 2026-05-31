from __future__ import annotations

import logging

from sqlalchemy import Engine, inspect, text
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

# Columns added in v1.3.14 to fix the v1.1.6 silent bug (PhaseCompleted
# emits cache_creation_input_tokens, cache_read_input_tokens, cache_hit_rate
# but SwPhase had no columns for them, so DB cache analytics were silently
# zero). For existing SQLite DBs, ALTER TABLE ADD COLUMN is idempotent via
# the table-inspection guard below; for postgres/mysql the same path works.
_ADDITIVE_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("sw_phases", "cache_creation_input_tokens", "INTEGER DEFAULT 0 NOT NULL"),
    ("sw_phases", "cache_read_input_tokens", "INTEGER DEFAULT 0 NOT NULL"),
    ("sw_phases", "cache_hit_rate", "FLOAT DEFAULT 0.0 NOT NULL"),
)


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


def ensure_schema_current(engine: Engine) -> list[str]:
    """Apply additive ALTER TABLE migrations idempotently.

    Called after Base.metadata.create_all to bring existing DBs forward.
    create_all only adds tables that don't exist; columns added to an
    existing table need explicit ALTER TABLE ADD COLUMN. Each entry in
    _ADDITIVE_MIGRATIONS is guarded by an inspector check so re-runs
    are no-ops.

    Returns the list of (table.column) pairs added in this call —
    callers can log them, tests can assert on them.
    """
    inspector = inspect(engine)
    added: list[str] = []
    for table, column, type_decl in _ADDITIVE_MIGRATIONS:
        if not inspector.has_table(table):
            # New install — create_all will produce the column from the
            # model definition; no ALTER needed.
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        if column in existing:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {type_decl}"))
            added.append(f"{table}.{column}")
            logger.info("schema migration: added %s.%s (%s)", table, column, type_decl)
        except Exception as exc:
            logger.warning(
                "schema migration: ALTER TABLE %s ADD COLUMN %s failed: %s",
                table,
                column,
                exc,
            )
    return added
