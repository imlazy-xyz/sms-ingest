"""app_config key/value table access."""

from __future__ import annotations

import psycopg
from psycopg.types.json import Json

RETENTION_KEY = "retention_days"


def get_retention_days(conn: psycopg.Connection, default: int) -> int:
    row = conn.execute(
        "select value from app_config where key = %s", (RETENTION_KEY,)
    ).fetchone()
    if row is None or row["value"] is None:
        return default
    return int(row["value"])


def set_retention_days(conn: psycopg.Connection, days: int) -> None:
    conn.execute(
        """
        insert into app_config (key, value, updated_at)
        values (%s, %s, now())
        on conflict (key) do update set value = excluded.value, updated_at = now()
        """,
        (RETENTION_KEY, Json(days)),
    )
