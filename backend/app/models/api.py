"""HTTP request/response models for the ingestion API.

``context_info`` is intentionally a raw dict: it is bound into the HPKE
ciphertext, so the backend must re-serialize exactly what the device sent
(see ``core.crypto.canonical_context_info``). Normalizing it through a typed
model could drop fields the device bound and break decryption.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EncryptionMeta(BaseModel):
    scheme: str
    server_key_id: str
    server_key_pin: str


class UploadBatchRequest(BaseModel):
    version: int
    device_time: str
    client_batch_id: str = Field(min_length=1)
    encryption: EncryptionMeta
    ciphertext: str = Field(min_length=1)
    context_info: dict[str, Any]


class RejectedItem(BaseModel):
    client_message_id: str
    reason: str


class NextSync(BaseModel):
    retry_after_seconds: int | None = None


class UploadResponse(BaseModel):
    status: Literal["accepted", "partial"]
    server_batch_id: str
    accepted_count: int
    duplicate_count: int
    rejected_count: int
    rejected: list[RejectedItem] = Field(default_factory=list)
    next_sync: NextSync = Field(default_factory=NextSync)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
