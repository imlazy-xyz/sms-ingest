"""Database access helpers (psycopg 3 + connection pool).

The pool is created lazily so that the health endpoint and unit tests do not
require a live database. Repositories receive an open connection and own the SQL.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import Settings, get_settings

_pool: ConnectionPool | None = None

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def get_pool(settings: Settings | None = None) -> ConnectionPool:
    global _pool
    if _pool is None:
        settings = settings or get_settings()
        _pool = ConnectionPool(
            conninfo=settings.require("database_url"),
            min_size=1,
            max_size=4,
            open=False,
            # autocommit=True: bare statements commit immediately and each
            # `with conn.transaction()` block is its own durable transaction. This
            # keeps audit-on-reject writes committed even when the request then
            # raises an HTTP error.
            kwargs={"row_factory": dict_row, "autocommit": True},
        )
        _pool.open()
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connection(settings: Settings | None = None) -> Iterator[psycopg.Connection]:
    """Yield a pooled connection. Commit/rollback is the caller's responsibility
    (use ``conn.transaction()`` for atomic units of work)."""
    with get_pool(settings).connection() as conn:
        yield conn


def apply_migrations(conn: psycopg.Connection) -> None:
    """Apply SQL migrations in filename order. Each file is idempotent
    (``create table if not exists`` / ``on conflict do nothing``)."""
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        with conn.transaction():
            conn.execute(sql)
