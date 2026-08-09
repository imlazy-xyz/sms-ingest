"""users table access."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg


def insert(conn: psycopg.Connection, *, display_name: str) -> dict[str, Any]:
    return conn.execute(
        """
        insert into users (display_name)
        values (%s)
        returning id, display_name, created_at
        """,
        (display_name,),
    ).fetchone()


def get_by_id(conn: psycopg.Connection, user_id: UUID | str) -> dict[str, Any] | None:
    return conn.execute(
        "select id, display_name, created_at from users where id = %s",
        (user_id,),
    ).fetchone()


def list_all(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return conn.execute(
        "select id, display_name, created_at from users order by display_name"
    ).fetchall()
