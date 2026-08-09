"""sim_assignments table access.

Interval-versioned map from (device_id, sub_id) to a numbers row. Exactly one
"open" (``effective_to is null``) row per ``(device_id, sub_id)`` at a time,
enforced by a partial unique index (migration 0002). Callers pick the right
operation (open, mutate-in-place, or close+open) — this module only exposes
the primitives; the case-selection logic lives in ``services.curation``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg


def get_current(
    conn: psycopg.Connection, *, device_id: UUID | str, sub_id: int
) -> dict[str, Any] | None:
    """The currently-open assignment for (device, subId), if any."""
    return conn.execute(
        """
        select id, device_id, sub_id, iccid, number_id, effective_from, effective_to
        from sim_assignments
        where device_id = %s and sub_id = %s and effective_to is null
        """,
        (device_id, sub_id),
    ).fetchone()


def list_for_device_sub(
    conn: psycopg.Connection, *, device_id: UUID | str, sub_id: int
) -> list[dict[str, Any]]:
    """All assignment intervals for (device, subId), oldest first — for
    picking the interval effective at a given message's own timestamp,
    not just whichever is currently open (see curation._resolve_rows)."""
    return conn.execute(
        """
        select id, device_id, sub_id, iccid, number_id, effective_from, effective_to
        from sim_assignments
        where device_id = %s and sub_id = %s
        order by effective_from
        """,
        (device_id, sub_id),
    ).fetchall()


def get_by_id(conn: psycopg.Connection, assignment_id: UUID | str) -> dict[str, Any] | None:
    return conn.execute(
        """
        select id, device_id, sub_id, iccid, number_id, effective_from, effective_to
        from sim_assignments where id = %s
        """,
        (assignment_id,),
    ).fetchone()


def open_new(
    conn: psycopg.Connection,
    *,
    device_id: UUID | str,
    sub_id: int,
    number_id: UUID | str,
    iccid: str | None = None,
) -> dict[str, Any]:
    """Insert a new open assignment. Fails (unique violation) if one is
    already open for this (device, subId) — callers must close it first."""
    return conn.execute(
        """
        insert into sim_assignments (device_id, sub_id, number_id, iccid)
        values (%s, %s, %s, %s)
        returning id, device_id, sub_id, iccid, number_id, effective_from, effective_to
        """,
        (device_id, sub_id, number_id, iccid),
    ).fetchone()


def close_current(
    conn: psycopg.Connection, *, device_id: UUID | str, sub_id: int
) -> int:
    """Close the currently-open assignment for (device, subId), if any."""
    cur = conn.execute(
        """
        update sim_assignments
        set effective_to = now()
        where device_id = %s and sub_id = %s and effective_to is null
        """,
        (device_id, sub_id),
    )
    return cur.rowcount


def update_number_in_place(
    conn: psycopg.Connection, *, assignment_id: UUID | str, number_id: UUID | str
) -> int:
    """Mutate an existing (normally still-open) row's target number in place —
    for correcting a mislabel, where the original interval was never real."""
    cur = conn.execute(
        "update sim_assignments set number_id = %s where id = %s",
        (number_id, assignment_id),
    )
    return cur.rowcount


def reassign(
    conn: psycopg.Connection,
    *,
    device_id: UUID | str,
    sub_id: int,
    new_number_id: UUID | str,
    iccid: str | None = None,
) -> dict[str, Any]:
    """Legitimate reassignment: close the old open interval (if any) and open
    a new one, in the same transaction. Past sms_records stamps are left
    alone — they genuinely belonged to the old number."""
    close_current(conn, device_id=device_id, sub_id=sub_id)
    return open_new(
        conn, device_id=device_id, sub_id=sub_id, number_id=new_number_id, iccid=iccid
    )


def list_for_device(conn: psycopg.Connection, device_id: UUID | str) -> list[dict[str, Any]]:
    return conn.execute(
        """
        select id, device_id, sub_id, iccid, number_id, effective_from, effective_to
        from sim_assignments where device_id = %s
        order by sub_id, effective_from
        """,
        (device_id,),
    ).fetchall()
