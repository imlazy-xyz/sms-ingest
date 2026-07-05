"""Encrypted SMS batch ingestion workflow.

Order of operations (fail closed, audit everything):

1. Validate encryption metadata (scheme, key id, key pin) — before any DB write.
2. Validate the bound ``context_info`` for consistency.
3. Decrypt the HPKE ciphertext with the canonical context bytes.
4. Parse the plaintext JSON envelope.
5. In one transaction: reserve the batch (idempotent on client_batch_id),
   validate + encrypt + insert each message (dedupe via unique constraint),
   finalize counts, and write audit events.

Hard failures in steps 1-4 raise :class:`BatchRejected` (HTTP 400) and are
audited as ``upload.rejected`` without persisting a batch row, so the device can
safely resend. Per-message problems are reported in the response's ``rejected``
list, not as batch failures.

Never log SMS plaintext, decrypted payloads, tokens, or key material.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg

from app.context import AppContext
from app.core import audit, crypto, dedupe, field_crypto, tokens
from app.models.api import UploadBatchRequest
from app.models.domain import BatchResult, Device, ParsedMessage, RejectedMessage
from app.repositories import app_config, sms_records, upload_batches

logger = logging.getLogger("sms_ingest.ingestion")


class BatchRejected(Exception):
    """Whole-batch rejection (maps to HTTP 400)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _audit_reject(
    conn: psycopg.Connection, device: Device, client_batch_id: str, reason: str
) -> None:
    with conn.transaction():
        audit.record(
            conn,
            audit.UPLOAD_REJECTED,
            actor_type=audit.ACTOR_DEVICE,
            device_id=device.id,
            metadata={"client_batch_id": client_batch_id, "reason": reason},
        )


def _reject(
    conn: psycopg.Connection, device: Device, client_batch_id: str, reason: str
) -> None:
    _audit_reject(conn, device, client_batch_id, reason)
    logger.info("batch_rejected device=%s reason=%s", device.token_prefix, reason)
    raise BatchRejected(reason)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _validate_message(raw: Any) -> tuple[ParsedMessage | None, RejectedMessage | None]:
    if not isinstance(raw, dict):
        return None, RejectedMessage("unknown", "invalid_message")
    cmid = raw.get("client_message_id")
    cmid = cmid if isinstance(cmid, str) and cmid else "unknown"

    if raw.get("direction") != "inbox":
        return None, RejectedMessage(cmid, "invalid_direction")

    dedupe_id = raw.get("dedupe_id")
    if not isinstance(dedupe_id, str) or not dedupe_id:
        return None, RejectedMessage(cmid, "missing_field")

    sender = raw.get("sender")
    if not isinstance(sender, str) or not sender:
        return None, RejectedMessage(cmid, "missing_field")

    body = raw.get("body")
    if not isinstance(body, str):
        return None, RejectedMessage(cmid, "missing_field")

    received_at = _parse_timestamp(raw.get("sms_received_at"))
    if received_at is None:
        return None, RejectedMessage(cmid, "invalid_timestamp")

    thread_hint = raw.get("thread_hint")
    sim_info = raw.get("sim_info")
    return (
        ParsedMessage(
            client_message_id=cmid,
            dedupe_id=dedupe_id,
            direction="inbox",
            sender=sender,
            body=body,
            sms_received_at=received_at,
            thread_hint=thread_hint if isinstance(thread_hint, str) else None,
            sim_info=sim_info if isinstance(sim_info, str) else None,
        ),
        None,
    )


def _result_from_existing(row: dict[str, Any]) -> BatchResult:
    rejected: list[RejectedMessage] = []
    if row.get("error_summary"):
        for item in json.loads(row["error_summary"]):
            rejected.append(
                RejectedMessage(item["client_message_id"], item["reason"])
            )
    status = row["status"] if row["status"] in ("accepted", "partial") else "accepted"
    return BatchResult(
        server_batch_id=str(row["id"]),
        status=status,
        accepted_count=row["accepted_count"],
        duplicate_count=row["duplicate_count"],
        rejected_count=row["rejected_count"],
        rejected=rejected,
    )


def ingest_batch(
    conn: psycopg.Connection,
    ctx: AppContext,
    device: Device,
    request: UploadBatchRequest,
) -> BatchResult:
    client_batch_id = request.client_batch_id

    # 1. Encryption metadata.
    enc = request.encryption
    if enc.scheme != ctx.expected_scheme:
        _reject(conn, device, client_batch_id, "unsupported_scheme")
    if enc.server_key_id != ctx.server_key_id:
        _reject(conn, device, client_batch_id, "unknown_key_id")
    if not tokens.tokens_equal(enc.server_key_pin, ctx.server_key_pin):
        _reject(conn, device, client_batch_id, "key_pin_mismatch")

    # 2. Bound context_info sanity.
    ci = request.context_info
    if ci.get("payload_type") != "sms_batch":
        _reject(conn, device, client_batch_id, "invalid_context")
    if ci.get("client_batch_id") != client_batch_id:
        _reject(conn, device, client_batch_id, "context_batch_id_mismatch")
    if ctx.api_base_url and ci.get("api_base_url") != ctx.api_base_url:
        _reject(conn, device, client_batch_id, "api_base_url_mismatch")

    # 3. Decrypt.
    context_bytes = crypto.canonical_context_info(ci)
    try:
        plaintext = crypto.decrypt_batch(
            ctx.hybrid_decrypt, request.ciphertext, context_bytes
        )
    except crypto.CryptoError:
        _reject(conn, device, client_batch_id, "decrypt_failed")

    # 4. Parse plaintext envelope.
    try:
        payload = json.loads(plaintext)
        messages = payload["messages"]
    except (json.JSONDecodeError, KeyError, TypeError):
        _reject(conn, device, client_batch_id, "invalid_payload")
    if not isinstance(messages, list):
        _reject(conn, device, client_batch_id, "invalid_payload")

    # 5. Reserve batch + process, atomically.
    with conn.transaction():
        created = upload_batches.create_processing(conn, device.id, client_batch_id)
        if created is None:
            existing = upload_batches.get_by_client_batch_id(
                conn, device.id, client_batch_id
            )
            logger.info(
                "batch_replayed device=%s messages=%d", device.token_prefix, len(messages)
            )
            return _result_from_existing(existing)

        batch_id = created["id"]
        audit.record(
            conn,
            audit.BATCH_DECRYPTED,
            actor_type=audit.ACTOR_DEVICE,
            device_id=device.id,
            metadata={"client_batch_id": client_batch_id, "message_count": len(messages)},
        )

        retention_days = app_config.get_retention_days(conn, ctx.retention_days_default)
        accepted = duplicate = 0
        rejected: list[RejectedMessage] = []

        for raw in messages:
            parsed, rej = _validate_message(raw)
            if rej is not None:
                rejected.append(rej)
                continue
            expires_at = parsed.sms_received_at + timedelta(days=retention_days)
            inserted = sms_records.insert_ignore_duplicate(
                conn,
                device_id=device.id,
                upload_batch_id=batch_id,
                dedupe_id=parsed.dedupe_id,
                sms_received_at=parsed.sms_received_at,
                direction=parsed.direction,
                sender_enc=field_crypto.encrypt_field(ctx.field_aead, "sender", parsed.sender),
                body_enc=field_crypto.encrypt_field(ctx.field_aead, "body", parsed.body),
                thread_hint_enc=field_crypto.encrypt_field(
                    ctx.field_aead, "thread_hint", parsed.thread_hint
                ),
                sim_info_enc=field_crypto.encrypt_field(
                    ctx.field_aead, "sim_info", parsed.sim_info
                ),
                expires_at=expires_at,
            )
            if inserted:
                accepted += 1
            else:
                duplicate += 1

        status = "accepted" if not rejected else "partial"
        error_summary = (
            json.dumps([{"client_message_id": r.client_message_id, "reason": r.reason} for r in rejected])
            if rejected
            else None
        )
        upload_batches.finalize(
            conn,
            batch_id,
            status=status,
            accepted_count=accepted,
            duplicate_count=duplicate,
            rejected_count=len(rejected),
            error_summary=error_summary,
        )
        if duplicate:
            audit.record(
                conn,
                audit.SMS_DUPLICATE_DETECTED,
                actor_type=audit.ACTOR_DEVICE,
                device_id=device.id,
                metadata={"client_batch_id": client_batch_id, "duplicate_count": duplicate},
            )
        audit.record(
            conn,
            audit.UPLOAD_ACCEPTED,
            actor_type=audit.ACTOR_DEVICE,
            device_id=device.id,
            metadata={
                "client_batch_id": client_batch_id,
                "server_batch_id": str(batch_id),
                "accepted_count": accepted,
                "duplicate_count": duplicate,
                "rejected_count": len(rejected),
            },
        )

    logger.info(
        "batch_ingested device=%s accepted=%d duplicate=%d rejected=%d",
        device.token_prefix,
        accepted,
        duplicate,
        len(rejected),
    )
    return BatchResult(
        server_batch_id=str(batch_id),
        status=status,
        accepted_count=accepted,
        duplicate_count=duplicate,
        rejected_count=len(rejected),
        rejected=rejected,
    )
