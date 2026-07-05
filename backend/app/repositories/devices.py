"""devices table access."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg


def insert(
    conn: psycopg.Connection,
    *,
    label: str,
    token_prefix: str,
    token_hash: str,
    dedupe_secret_enc: bytes | None = None,
    status: str = "active",
) -> dict[str, Any]:
    return conn.execute(
        """
        insert into devices (label, token_prefix, token_hash, dedupe_secret_enc, status)
        values (%s, %s, %s, %s, %s)
        returning id, label, status, token_prefix, created_at
        """,
        (label, token_prefix, token_hash, dedupe_secret_enc, status),
    ).fetchone()


def get_by_token_hash(
    conn: psycopg.Connection, token_hash: str
) -> dict[str, Any] | None:
    return conn.execute(
        "select id, label, status, token_prefix, revoked_at "
        "from devices where token_hash = %s",
        (token_hash,),
    ).fetchone()


def get_by_id(conn: psycopg.Connection, device_id: UUID | str) -> dict[str, Any] | None:
    return conn.execute(
        "select id, label, status, token_prefix, revoked_at "
        "from devices where id = %s",
        (device_id,),
    ).fetchone()


def revoke(conn: psycopg.Connection, device_id: UUID | str) -> int:
    cur = conn.execute(
        "update devices set status = 'revoked', revoked_at = now() "
        "where id = %s and status <> 'revoked'",
        (device_id,),
    )
    return cur.rowcount


def rotate_token(
    conn: psycopg.Connection,
    device_id: UUID | str,
    *,
    token_prefix: str,
    token_hash: str,
) -> int:
    cur = conn.execute(
        "update devices set token_prefix = %s, token_hash = %s, "
        "status = 'active', revoked_at = null where id = %s",
        (token_prefix, token_hash, device_id),
    )
    return cur.rowcount


def touch_last_seen(conn: psycopg.Connection, device_id: UUID | str) -> None:
    conn.execute(
        "update devices set last_seen_at = now() where id = %s", (device_id,)
    )
