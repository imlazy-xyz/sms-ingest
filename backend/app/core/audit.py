"""Security audit event helpers.

Metadata passed here must be non-sensitive (counts, ids, reasons). Never include
SMS plaintext, decrypted payloads, tokens, or key material.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg

from app.repositories import audit_events

# Required event types (see backend-plan.md).
DEVICE_CREATED = "device.created"
DEVICE_REVOKED = "device.revoked"
DEVICE_TOKEN_ROTATED = "device.token_rotated"
UPLOAD_ACCEPTED = "upload.accepted"
UPLOAD_REJECTED = "upload.rejected"
BATCH_DECRYPTED = "batch.decrypted"
SMS_DUPLICATE_DETECTED = "sms.duplicate_detected"
RETENTION_DELETED = "retention.deleted"
USER_CREATED = "user.created"
NUMBER_CREATED = "number.created"
SIM_ASSIGNED = "sim.assigned"
SIM_ASSIGNMENT_CORRECTED = "sim.assignment_corrected"
SIM_REASSIGNED = "sim.reassigned"
OWNERSHIP_RESOLVED = "ownership.resolved"
NUMBER_OWNER_REASSIGNED = "number.owner_reassigned"

# Reader (admin read-only UI) events. Every decrypt-read in the reader records
# exactly one sanitized row of this type. Metadata is who/when/scope/counts
# only — never SMS content, senders, bodies, tokens, or keys.
READ_PERFORMED = "read.performed"

ACTOR_DEVICE = "device"
ACTOR_ADMIN = "admin"
ACTOR_SYSTEM = "system"


def record(
    conn: psycopg.Connection,
    event_type: str,
    *,
    actor_type: str,
    device_id: UUID | str | None = None,
    actor_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    audit_events.insert(
        conn,
        event_type,
        actor_type=actor_type,
        device_id=device_id,
        actor_id=actor_id,
        metadata=metadata,
    )
