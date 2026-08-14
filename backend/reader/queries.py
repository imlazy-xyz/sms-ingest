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


def last_activity_by_owner_user(conn: psycopg.Connection, user_id: UUID | str) -> Any:
    """Most recent ``sms_received_at`` across every number owned by this user,
    or ``None`` if they have no messages yet. ``sms_received_at`` is a plain
    (unencrypted) column, so this is a cheap indexed aggregate -- no decrypt
    needed."""
    row = conn.execute(
        """
        select max(r.sms_received_at) as last_activity
        from sms_records r
        join numbers n on n.id = r.owner_number_id
        where n.user_id = %s
        """,
        (user_id,),
    ).fetchone()
    return row["last_activity"]


def search_structural(conn: psycopg.Connection, query: str) -> list[dict[str, Any]]:
    """Narrow, structural lookup across cleartext identity columns only --
    ``users.display_name``, ``numbers.e164``, ``numbers.label``. Never touches
    ``sender_enc``/``body_enc``; this is jump-to-the-right-record navigation,
    not the (deliberately deferred) full-text message search."""
    needle = f"%{query}%"
    return conn.execute(
        """
        select 'user' as kind, u.id as user_id, u.display_name,
               null::uuid as number_id, null as e164, null as label
        from users u
        where u.display_name ilike %s
        union all
        select 'number' as kind, n.user_id, u.display_name,
               n.id as number_id, n.e164, n.label
        from numbers n
        join users u on u.id = n.user_id
        where n.e164 ilike %s or n.label ilike %s
        order by display_name
        """,
        (needle, needle, needle),
    ).fetchall()


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
