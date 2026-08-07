"""sms_records table access."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import psycopg


@dataclass
class RecordToInsert:
    dedupe_id: str
    sms_received_at: datetime
    direction: str
    sender_enc: bytes
    body_enc: bytes
    thread_hint_enc: bytes | None
    sim_info_enc: bytes | None
    expires_at: datetime


def insert_many_ignore_duplicates(
    conn: psycopg.Connection,
    *,
    device_id: UUID | str,
    upload_batch_id: UUID | str,
    records: list[RecordToInsert],
) -> set[str]:
    """Insert all ``records`` in a single round-trip. Returns the set of
    ``dedupe_id``s that were actually inserted; any ``dedupe_id`` not in the
    returned set collided with an existing ``(device_id, dedupe_id)`` (a
    duplicate). One multi-row ``INSERT`` instead of one round-trip per
    message — a batch of ~700 messages as individual sequential inserts over
    the Supabase session pooler was slow enough to blow past even a
    generous client read timeout, even though the transaction itself
    completed and committed fine (see `projects/sms-ingest/open-questions.md`,
    2026-08-07 debug session)."""
    if not records:
        return set()

    values_sql = ", ".join(["(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"] * len(records))
    params: list[object] = []
    for r in records:
        params.extend(
            [
                device_id,
                upload_batch_id,
                r.dedupe_id,
                r.sms_received_at,
                r.direction,
                r.sender_enc,
                r.body_enc,
                r.thread_hint_enc,
                r.sim_info_enc,
                r.expires_at,
            ]
        )

    rows = conn.execute(
        f"""
        insert into sms_records (
            device_id, upload_batch_id, dedupe_id, sms_received_at, direction,
            sender_enc, body_enc, thread_hint_enc, sim_info_enc, expires_at
        )
        values {values_sql}
        on conflict (device_id, dedupe_id) do nothing
        returning dedupe_id
        """,
        params,
    ).fetchall()
    return {row["dedupe_id"] for row in rows}


def delete_expired(conn: psycopg.Connection, now: datetime) -> int:
    cur = conn.execute("delete from sms_records where expires_at <= %s", (now,))
    return cur.rowcount


def count_for_device(conn: psycopg.Connection, device_id: UUID | str) -> int:
    row = conn.execute(
        "select count(*) as n from sms_records where device_id = %s", (device_id,)
    ).fetchone()
    return int(row["n"])
