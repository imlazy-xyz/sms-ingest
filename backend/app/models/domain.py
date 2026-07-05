"""Internal domain types (not wire-facing)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Device:
    id: UUID
    label: str
    status: str
    token_prefix: str
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class ParsedMessage:
    client_message_id: str
    dedupe_id: str
    direction: str
    sender: str
    body: str
    sms_received_at: datetime
    thread_hint: str | None = None
    sim_info: str | None = None


@dataclass
class RejectedMessage:
    client_message_id: str
    reason: str


@dataclass
class BatchResult:
    server_batch_id: str
    status: str
    accepted_count: int = 0
    duplicate_count: int = 0
    rejected_count: int = 0
    rejected: list[RejectedMessage] = field(default_factory=list)
