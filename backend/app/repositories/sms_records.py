"""sms_records table access."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import psycopg


def insert_ignore_duplicate(
    conn: psycopg.Connection,
    *,
    device_id: UUID | str,
    upload_batch_id: UUID | str,
    dedupe_id: str,
    sms_received_at: datetime,
    direction: str,
    sender_enc: bytes,
    body_enc: bytes,
    thread_hint_enc: bytes | None,
    sim_info_enc: bytes | None,
    expires_at: datetime,
) -> bool:
    """Insert one record. Returns ``True`` if inserted, ``False`` if it collided
    with an existing ``(device_id, dedupe_id)`` (a duplicate)."""
    row = conn.execute(
        """
        insert into sms_records (
            device_id, upload_batch_id, dedupe_id, sms_received_at, direction,
            sender_enc, body_enc, thread_hint_enc, sim_info_enc, expires_at
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (device_id, dedupe_id) do nothing
        returning id
        """,
        (
            device_id,
            upload_batch_id,
            dedupe_id,
            sms_received_at,
            direction,
            sender_enc,
            body_enc,
            thread_hint_enc,
            sim_info_enc,
            expires_at,
        ),
    ).fetchone()
    return row is not None


def delete_expired(conn: psycopg.Connection, now: datetime) -> int:
    cur = conn.execute("delete from sms_records where expires_at <= %s", (now,))
    return cur.rowcount


def count_for_device(conn: psycopg.Connection, device_id: UUID | str) -> int:
    row = conn.execute(
        "select count(*) as n from sms_records where device_id = %s", (device_id,)
    ).fetchone()
    return int(row["n"])
