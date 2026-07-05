"""upload_batches table access."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg


def create_processing(
    conn: psycopg.Connection, device_id: UUID | str, client_batch_id: str
) -> dict[str, Any] | None:
    """Insert a new batch row in 'processing' state. Returns the row, or ``None``
    if ``(device_id, client_batch_id)`` already exists (idempotent replay)."""
    return conn.execute(
        """
        insert into upload_batches (device_id, client_batch_id, status)
        values (%s, %s, 'processing')
        on conflict (device_id, client_batch_id) do nothing
        returning id
        """,
        (device_id, client_batch_id),
    ).fetchone()


def get_by_client_batch_id(
    conn: psycopg.Connection, device_id: UUID | str, client_batch_id: str
) -> dict[str, Any] | None:
    return conn.execute(
        """
        select id, status, accepted_count, duplicate_count, rejected_count, error_summary
        from upload_batches
        where device_id = %s and client_batch_id = %s
        """,
        (device_id, client_batch_id),
    ).fetchone()


def finalize(
    conn: psycopg.Connection,
    batch_id: UUID | str,
    *,
    status: str,
    accepted_count: int,
    duplicate_count: int,
    rejected_count: int,
    error_summary: str | None = None,
) -> None:
    conn.execute(
        """
        update upload_batches
        set status = %s, accepted_count = %s, duplicate_count = %s,
            rejected_count = %s, error_summary = %s
        where id = %s
        """,
        (status, accepted_count, duplicate_count, rejected_count, error_summary, batch_id),
    )
