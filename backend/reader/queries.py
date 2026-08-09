"""Read-only SQL the reader needs beyond ``app.repositories``.

The shared repositories cover the ownership-narrowing queries; this module adds
only the small read-side lookups they do not expose (a devices listing with
``last_seen_at``, and a few counts for index pages). SQL stays here rather than
in ``reader.service`` or ``reader.routes`` so the layering matches the rest of
the backend: routes own HTTP, services own workflow, SQL lives in one place.

Everything here is ``select``-only and returns still-encrypted columns where a
column is encrypted; decryption is ``reader.service``'s job.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg


def list_devices(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return conn.execute(
        """
        select id, label, status, token_prefix, created_at, last_seen_at, revoked_at
        from devices
        order by label
        """
    ).fetchall()


def get_device(conn: psycopg.Connection, device_id: UUID | str) -> dict[str, Any] | None:
    return conn.execute(
        """
        select id, label, status, token_prefix, created_at, last_seen_at, revoked_at
        from devices
        where id = %s
        """,
        (device_id,),
    ).fetchone()


def count_by_owner_number(conn: psycopg.Connection, number_id: UUID | str) -> int:
    row = conn.execute(
        "select count(*) as n from sms_records where owner_number_id = %s",
        (number_id,),
    ).fetchone()
    return int(row["n"])


def count_by_owner_user(conn: psycopg.Connection, user_id: UUID | str) -> int:
    row = conn.execute(
        """
        select count(*) as n
        from sms_records r
        join numbers n on n.id = r.owner_number_id
        where n.user_id = %s
        """,
        (user_id,),
    ).fetchone()
    return int(row["n"])


def count_unassigned(
    conn: psycopg.Connection, *, device_id: UUID | str | None = None
) -> int:
    if device_id is not None:
        row = conn.execute(
            "select count(*) as n from sms_records "
            "where owner_number_id is null and device_id = %s",
            (device_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "select count(*) as n from sms_records where owner_number_id is null"
        ).fetchone()
    return int(row["n"])
