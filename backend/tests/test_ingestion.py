"""Ingestion tests (integration: require Postgres via pg_conn)."""

from __future__ import annotations

import pytest

from app.core import field_crypto, tokens
from app.models.domain import Device
from app.services import ingestion

API = "https://sms-api.example.com"


def _device(conn, keys, *, label="phone", raw="tok"):
    row = tokens.token_prefix(raw)
    from app.repositories import devices

    inserted = devices.insert(
        conn,
        label=label,
        token_prefix=row,
        token_hash=tokens.hash_token(raw, keys["pepper"]),
    )
    return Device(id=inserted["id"], label=label, status="active", token_prefix=row)


def _audit(conn) -> dict[str, int]:
    rows = conn.execute(
        "select event_type, count(*) n from audit_events group by event_type"
    ).fetchall()
    return {r["event_type"]: int(r["n"]) for r in rows}


def _sms_count(conn, device_id) -> int:
    return conn.execute(
        "select count(*) n from sms_records where device_id=%s", (device_id,)
    ).fetchone()["n"]


def test_happy_path_stores_encrypted_and_audits(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    req = make_request([make_message(dedupe_id="d1", sender="+1999", body="hi")])

    result = ingestion.ingest_batch(pg_conn, ctx, device, req)

    assert (result.accepted_count, result.duplicate_count, result.rejected_count) == (1, 0, 0)
    assert result.status == "accepted"

    row = pg_conn.execute(
        "select sender_enc, body_enc, direction from sms_records where device_id=%s",
        (device.id,),
    ).fetchone()
    assert bytes(row["body_enc"]) != b"hi"  # stored encrypted, not plaintext
    assert field_crypto.decrypt_field(ctx.field_aead, "body", row["body_enc"]) == "hi"
    assert field_crypto.decrypt_field(ctx.field_aead, "sender", row["sender_enc"]) == "+1999"

    counts = _audit(pg_conn)
    assert counts.get("batch.decrypted") == 1
    assert counts.get("upload.accepted") == 1


def test_duplicate_across_batches_is_deduped(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    ingestion.ingest_batch(
        pg_conn, ctx, device, make_request([make_message(dedupe_id="d1")], client_batch_id="b1")
    )
    result = ingestion.ingest_batch(
        pg_conn, ctx, device, make_request([make_message(dedupe_id="d1")], client_batch_id="b2")
    )
    assert (result.accepted_count, result.duplicate_count) == (0, 1)
    assert _sms_count(pg_conn, device.id) == 1
    assert _audit(pg_conn).get("sms.duplicate_detected") == 1


def test_same_batch_replay_is_idempotent(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    req = make_request([make_message(dedupe_id="d1")], client_batch_id="b1")
    first = ingestion.ingest_batch(pg_conn, ctx, device, req)
    second = ingestion.ingest_batch(pg_conn, ctx, device, req)
    assert first.accepted_count == 1
    assert second.accepted_count == 1  # returns stored result
    assert second.duplicate_count == 0
    assert _sms_count(pg_conn, device.id) == 1


def test_partial_rejects_bad_message(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    messages = [
        make_message(dedupe_id="d1", client_message_id="ok"),
        make_message(dedupe_id="d2", client_message_id="bad", sms_received_at="not-a-date"),
    ]
    result = ingestion.ingest_batch(pg_conn, ctx, device, make_request(messages))
    assert result.status == "partial"
    assert result.accepted_count == 1
    assert result.rejected_count == 1
    assert result.rejected[0].client_message_id == "bad"
    assert result.rejected[0].reason == "invalid_timestamp"


def test_rejects_non_inbox_direction(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    result = ingestion.ingest_batch(
        pg_conn,
        ctx,
        device,
        make_request([make_message(direction="sent", client_message_id="s1")]),
    )
    assert result.rejected_count == 1
    assert result.rejected[0].reason == "invalid_direction"


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"scheme": "bogus"}, "unsupported_scheme"),
        ({"server_key_id": "other"}, "unknown_key_id"),
        ({"server_key_pin": "deadbeef"}, "key_pin_mismatch"),
    ],
)
def test_metadata_rejections(pg_conn, ctx, keys, make_request, make_message, kwargs, reason):
    device = _device(pg_conn, keys)
    with pytest.raises(ingestion.BatchRejected) as exc:
        ingestion.ingest_batch(pg_conn, ctx, device, make_request([make_message()], **kwargs))
    assert exc.value.reason == reason
    assert _audit(pg_conn).get("upload.rejected") == 1  # rejection is audited


def test_malformed_ciphertext_rejected(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    with pytest.raises(ingestion.BatchRejected) as exc:
        ingestion.ingest_batch(
            pg_conn, ctx, device, make_request([make_message()], ciphertext="AAAA")
        )
    assert exc.value.reason == "decrypt_failed"


def test_context_binding_tamper_rejected(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    base = {"api_base_url": API, "payload_type": "sms_batch", "version": 1, "client_batch_id": "b1"}
    tampered = dict(base, extra="tamper")  # passes step-2 checks, changes bound bytes
    req = make_request(
        [make_message()], client_batch_id="b1", context_info=tampered, encrypt_context=base
    )
    with pytest.raises(ingestion.BatchRejected) as exc:
        ingestion.ingest_batch(pg_conn, ctx, device, req)
    assert exc.value.reason == "decrypt_failed"


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"payload_type": "wrong"}, "invalid_context"),
        ({"client_batch_id": "mismatch"}, "context_batch_id_mismatch"),
        ({"api_base_url": "https://evil.example.com"}, "api_base_url_mismatch"),
    ],
)
def test_context_consistency_rejections(pg_conn, ctx, keys, make_request, make_message, overrides, reason):
    device = _device(pg_conn, keys)
    base = {"api_base_url": API, "payload_type": "sms_batch", "version": 1, "client_batch_id": "b1"}
    ci = dict(base, **overrides)
    req = make_request(
        [make_message()], client_batch_id="b1", context_info=ci, encrypt_context=ci
    )
    with pytest.raises(ingestion.BatchRejected) as exc:
        ingestion.ingest_batch(pg_conn, ctx, device, req)
    assert exc.value.reason == reason


# --- HTTP layer -------------------------------------------------------------


def test_endpoint_happy_path(client, pg_conn, keys, make_request, make_message):
    from app.repositories import devices

    devices.insert(
        pg_conn,
        label="p",
        token_prefix=tokens.token_prefix("raw-http"),
        token_hash=tokens.hash_token("raw-http", keys["pepper"]),
    )
    req = make_request([make_message(dedupe_id="d1")])
    resp = client.post(
        "/v1/uploads/sms-batches",
        headers={"Authorization": "Bearer raw-http"},
        json=req.model_dump(),
    )
    assert resp.status_code == 200
    assert resp.json()["accepted_count"] == 1


def test_endpoint_requires_auth(client, make_request, make_message):
    req = make_request([make_message()])
    resp = client.post("/v1/uploads/sms-batches", json=req.model_dump())
    assert resp.status_code == 401
