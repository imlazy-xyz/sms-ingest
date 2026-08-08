"""numbers table access."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg


def insert(
    conn: psycopg.Connection,
    *,
    e164: str,
    user_id: UUID | str,
    label: str | None = None,
    iccid: str | None = None,
) -> dict[str, Any]:
    return conn.execute(
        """
        insert into numbers (e164, user_id, label, iccid)
        values (%s, %s, %s, %s)
        returning id, e164, user_id, label, iccid, created_at
        """,
        (e164, user_id, label, iccid),
    ).fetchone()


def get_by_id(conn: psycopg.Connection, number_id: UUID | str) -> dict[str, Any] | None:
    return conn.execute(
        "select id, e164, user_id, label, iccid, created_at from numbers where id = %s",
        (number_id,),
    ).fetchone()


def get_by_e164(conn: psycopg.Connection, e164: str) -> dict[str, Any] | None:
    return conn.execute(
        "select id, e164, user_id, label, iccid, created_at from numbers where e164 = %s",
        (e164,),
    ).fetchone()


def list_all(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return conn.execute(
        "select id, e164, user_id, label, iccid, created_at from numbers order by e164"
    ).fetchall()


def list_for_user(conn: psycopg.Connection, user_id: UUID | str) -> list[dict[str, Any]]:
    return conn.execute(
        "select id, e164, user_id, label, iccid, created_at from numbers "
        "where user_id = %s order by e164",
        (user_id,),
    ).fetchall()


def set_user(conn: psycopg.Connection, number_id: UUID | str, user_id: UUID | str) -> int:
    """Reassign a number's current owner. Overwrite, no history kept (v1)."""
    cur = conn.execute(
        "update numbers set user_id = %s where id = %s",
        (user_id, number_id),
    )
    return cur.rowcount
