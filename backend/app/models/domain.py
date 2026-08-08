"""Internal domain types (not wire-facing)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class User:
    id: UUID
    display_name: str
    created_at: datetime | None = None


@dataclass(frozen=True)
class Number:
    id: UUID
    e164: str
    user_id: UUID
    label: str | None = None
    iccid: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class SimAssignment:
    id: UUID
    device_id: UUID
    sub_id: int
    number_id: UUID
    effective_from: datetime
    effective_to: datetime | None = None
    iccid: str | None = None


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
