"""Retention cleanup.

Deletes expired ``sms_records`` (``expires_at <= now``) and writes a
``retention.deleted`` audit event with the deleted count. Idempotent: running it
again after everything expired deletes nothing and records a zero-count event.
Never logs SMS plaintext.
"""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg

from app.core import audit
from app.repositories import sms_records


def run_cleanup(conn: psycopg.Connection, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    with conn.transaction():
        deleted = sms_records.delete_expired(conn, now)
        audit.record(
            conn,
            audit.RETENTION_DELETED,
            actor_type=audit.ACTOR_SYSTEM,
            metadata={"deleted_count": deleted, "cutoff": now.isoformat()},
        )
    return deleted
