"""audit_events table access."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Json


def insert(
    conn: psycopg.Connection,
    event_type: str,
    *,
    actor_type: str,
    device_id: UUID | str | None = None,
    actor_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Insert an audit event. ``metadata`` must contain only non-sensitive data
    (counts, ids, reasons) — never SMS plaintext, tokens, or key material."""
    conn.execute(
        """
        insert into audit_events (event_type, device_id, actor_type, actor_id, metadata)
        values (%s, %s, %s, %s, %s)
        """,
        (event_type, device_id, actor_type, actor_id, Json(metadata or {})),
    )
