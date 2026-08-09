"""sms_records table access."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
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


# --- Read-side query methods (still-encrypted rows; decryption is not this
# module's job) ---------------------------------------------------------

_SELECT_COLUMNS = (
    "id, device_id, sms_received_at, direction, sender_enc, body_enc, "
    "thread_hint_enc, sim_info_enc, owner_number_id"
)


def list_by_owner_number(
    conn: psycopg.Connection,
    number_id: UUID | str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return conn.execute(
        f"""
        select {_SELECT_COLUMNS}
        from sms_records
        where owner_number_id = %s
        order by sms_received_at desc
        limit %s offset %s
        """,
        (number_id, limit, offset),
    ).fetchall()


def list_by_owner_user(
    conn: psycopg.Connection,
    user_id: UUID | str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Narrow "by user" via the numbers.user_id join (user is derived, not
    stamped — see the ownership model docs)."""
    return conn.execute(
        f"""
        select r.id, r.device_id, r.sms_received_at, r.direction, r.sender_enc,
               r.body_enc, r.thread_hint_enc, r.sim_info_enc, r.owner_number_id
        from sms_records r
        join numbers n on n.id = r.owner_number_id
        where n.user_id = %s
        order by r.sms_received_at desc
        limit %s offset %s
        """,
        (user_id, limit, offset),
    ).fetchall()


def list_by_device(
    conn: psycopg.Connection,
    device_id: UUID | str,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    conditions = ["device_id = %s"]
    params: list[object] = [device_id]
    if since is not None:
        conditions.append("sms_received_at >= %s")
        params.append(since)
    if until is not None:
        conditions.append("sms_received_at <= %s")
        params.append(until)
    params.extend([limit, offset])
    return conn.execute(
        f"""
        select {_SELECT_COLUMNS}
        from sms_records
        where {" and ".join(conditions)}
        order by sms_received_at desc
        limit %s offset %s
        """,
        params,
    ).fetchall()


def list_unassigned_for_resolution(
    conn: psycopg.Connection,
    *,
    device_id: UUID | str | None = None,
    limit: int = 500,
    after: tuple[datetime, UUID | str] | None = None,
) -> list[dict[str, Any]]:
    """Candidate rows for a default (non-restamp) ``resolve`` pass: rows with
    no owner stamped yet. Scoped to a device when given.

    Paginated by a ``(sms_received_at, id)`` keyset cursor (``after``), not a
    plain ``LIMIT`` — rows that resolve to "unmapped" stay
    ``owner_number_id IS NULL`` and would otherwise re-fill every subsequent
    page's window forever, starving out later mapped rows. Callers (the
    resolve service) page through with ``after`` until a short page signals
    exhaustion, so every candidate row is visited exactly once per pass."""
    conditions = ["owner_number_id is null"]
    params: list[object] = []
    if device_id is not None:
        conditions.append("device_id = %s")
        params.append(device_id)
    if after is not None:
        conditions.append("(sms_received_at, id) > (%s, %s)")
        params.extend(after)
    params.append(limit)
    return conn.execute(
        f"""
        select {_SELECT_COLUMNS}
        from sms_records
        where {" and ".join(conditions)}
        order by sms_received_at, id
        limit %s
        """,
        params,
    ).fetchall()


def list_for_restamp(
    conn: psycopg.Connection,
    *,
    device_id: UUID | str | None = None,
    number_id: UUID | str | None = None,
    limit: int = 500,
    after: tuple[datetime, UUID | str] | None = None,
) -> list[dict[str, Any]]:
    """Candidate rows for ``resolve --restamp``: recompute over already-stamped
    rows too. Scoped by device and/or current owner number. Paginated by the
    same ``(sms_received_at, id)`` keyset cursor as
    :func:`list_unassigned_for_resolution`, for the same exhaustion reason."""
    conditions: list[str] = []
    params: list[object] = []
    if device_id is not None:
        conditions.append("device_id = %s")
        params.append(device_id)
    if number_id is not None:
        conditions.append("owner_number_id = %s")
        params.append(number_id)
    if after is not None:
        conditions.append("(sms_received_at, id) > (%s, %s)")
        params.extend(after)
    where = f"where {' and '.join(conditions)}" if conditions else ""
    params.append(limit)
    return conn.execute(
        f"""
        select {_SELECT_COLUMNS}
        from sms_records
        {where}
        order by sms_received_at, id
        limit %s
        """,
        params,
    ).fetchall()


def list_distinct_sim_info_by_device(
    conn: psycopg.Connection,
    device_id: UUID | str,
    *,
    limit: int = 5000,
    after_id: UUID | str | None = None,
) -> list[dict[str, Any]]:
    """All rows with a non-null sim_info_enc for a device, for
    ``list-observed-sims`` to decrypt and enumerate distinct (device, subId)
    pairs. Not deduped at the DB (sim_info is encrypted) — dedup happens
    after decrypt, in the service layer. Paginated by an ``id`` cursor
    (``after_id``) so a device with more rows than one page's ``limit`` is
    still fully covered by repeated calls, not silently truncated."""
    if after_id is not None:
        return conn.execute(
            """
            select id, device_id, sim_info_enc
            from sms_records
            where device_id = %s and sim_info_enc is not null and id > %s
            order by id
            limit %s
            """,
            (device_id, after_id, limit),
        ).fetchall()
    return conn.execute(
        """
        select id, device_id, sim_info_enc
        from sms_records
        where device_id = %s and sim_info_enc is not null
        order by id
        limit %s
        """,
        (device_id, limit),
    ).fetchall()


def stamp_owner_number(
    conn: psycopg.Connection, record_id: UUID | str, owner_number_id: UUID | str
) -> int:
    cur = conn.execute(
        "update sms_records set owner_number_id = %s where id = %s",
        (owner_number_id, record_id),
    )
    return cur.rowcount


def clear_owner_number(conn: psycopg.Connection, record_id: UUID | str) -> int:
    """Used when a restamp finds no current mapping (subId now unmapped) —
    leave/return to NULL rather than leaving a stale stamp."""
    cur = conn.execute(
        "update sms_records set owner_number_id = null where id = %s",
        (record_id,),
    )
    return cur.rowcount
