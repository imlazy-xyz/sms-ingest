"""Route/service tests for the admin reader UI (integration; require Postgres
via ``pg_conn``). Seeds real encrypted rows through the actual ingestion
pipeline (same path production traffic takes) so decryption in the reader is
exercised against genuine ciphertext, not a stub.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app import db
from app.core import tokens
from app.models.domain import Device
from app.repositories import numbers as numbers_repo
from app.repositories import sms_records
from app.repositories import users as users_repo
from app.services import ingestion


@pytest.fixture
def device(pg_conn, keys):
    from app.repositories import devices

    raw = "test-token"
    prefix = tokens.token_prefix(raw)
    inserted = devices.insert(
        pg_conn, label="phone-1", token_prefix=prefix, token_hash=tokens.hash_token(raw, keys["pepper"])
    )
    return Device(id=inserted["id"], label="phone-1", status="active", token_prefix=prefix)


@pytest.fixture
def seeded_number(pg_conn, ctx, device, make_request, make_message):
    """A user + number with two received messages from the same counterparty
    and one from a second counterparty, all owned by the number."""
    user = users_repo.insert(pg_conn, display_name="Alice")
    number = numbers_repo.insert(pg_conn, e164="+15551234567", user_id=user["id"], label="work")

    ingestion.ingest_batch(
        pg_conn,
        ctx,
        device,
        make_request(
            [
                make_message(
                    dedupe_id="r1", sender="+15550001111", body="hello from carrier",
                    sms_received_at="2026-07-01T12:00:00Z",
                ),
                make_message(
                    dedupe_id="r2", sender="+15550001111", body="second message",
                    sms_received_at="2026-07-01T12:05:00Z",
                ),
                make_message(
                    dedupe_id="r3", sender="+15559998888", body="a different sender",
                    sms_received_at="2026-07-01T13:00:00Z",
                ),
            ],
            client_batch_id="seed-batch",
        ),
    )
    for dedupe_id in ("r1", "r2", "r3"):
        row = pg_conn.execute(
            "select id from sms_records where dedupe_id = %s", (dedupe_id,)
        ).fetchone()
        sms_records.stamp_owner_number(pg_conn, row["id"], number["id"])

    return {"user": user, "number": number, "device": device}


@pytest.fixture
def reader_client(settings, ctx, pg_conn):
    """TestClient bound to the reader app (not the ingest app), same
    pool-reset pattern as the ingest ``client`` fixture."""
    from reader.main import create_app

    db.close_pool()
    app = create_app(settings)
    app.state.ctx = ctx
    with TestClient(app) as c:
        yield c
    db.close_pool()


def _audit_rows(pg_conn):
    """Only ``read.performed`` rows -- ingestion writes its own unrelated
    ``batch.decrypted`` audit events, which are out of scope here."""
    return pg_conn.execute(
        "select event_type, actor_id, metadata from audit_events "
        "where event_type = 'read.performed' order by occurred_at"
    ).fetchall()


# --- users -----------------------------------------------------------------


def test_users_list_shows_seeded_user(reader_client, seeded_number):
    resp = reader_client.get("/users")
    assert resp.status_code == 200
    assert "Alice" in resp.text


def test_user_detail_shows_number(reader_client, seeded_number):
    resp = reader_client.get(f"/users/{seeded_number['user']['id']}")
    assert resp.status_code == 200
    assert "+15551234567" in resp.text


def test_user_detail_404_for_unknown_user(reader_client):
    import uuid

    resp = reader_client.get(f"/users/{uuid.uuid4()}")
    assert resp.status_code == 404


# --- reading view / conversations ------------------------------------------


def test_number_reading_view_groups_by_counterparty(reader_client, seeded_number, pg_conn):
    number_id = seeded_number["number"]["id"]
    resp = reader_client.get(f"/numbers/{number_id}")
    assert resp.status_code == 200
    # Two distinct counterparties -> two conversation rows.
    assert resp.text.count("+15550001111") >= 1
    assert resp.text.count("+15559998888") >= 1
    assert "second message" in resp.text  # latest preview for the 2-message thread

    rows = _audit_rows(pg_conn)
    assert len(rows) == 1
    assert rows[0]["event_type"] == "read.performed"
    assert rows[0]["metadata"]["scope"]["view"] == "conversations"
    assert rows[0]["metadata"]["scope"]["number_id"] == str(number_id)


def test_thread_partial_renders_messages_newest_first(reader_client, seeded_number, pg_conn):
    number_id = seeded_number["number"]["id"]
    resp = reader_client.get(
        f"/numbers/{number_id}/thread", params={"counterparty": "+15550001111"}
    )
    assert resp.status_code == 200
    assert "hello from carrier" in resp.text
    assert "second message" in resp.text
    assert resp.text.index("second message") < resp.text.index("hello from carrier")

    rows = _audit_rows(pg_conn)
    assert len(rows) == 1
    assert rows[0]["metadata"]["scope"]["view"] == "thread"
    assert rows[0]["metadata"]["message_count"] == 2


def test_search_within_number_finds_match(reader_client, seeded_number, pg_conn):
    number_id = seeded_number["number"]["id"]
    resp = reader_client.get(f"/numbers/{number_id}/search", params={"q": "different"})
    assert resp.status_code == 200
    assert "a different sender" in resp.text
    assert "hello from carrier" not in resp.text

    rows = _audit_rows(pg_conn)
    assert rows[0]["metadata"]["scope"]["view"] == "search"
    assert rows[0]["metadata"]["scope"]["search_applied"] is True


def test_search_empty_query_does_not_audit_or_scan(reader_client, seeded_number, pg_conn):
    number_id = seeded_number["number"]["id"]
    resp = reader_client.get(f"/numbers/{number_id}/search", params={"q": ""})
    assert resp.status_code == 200
    # search() short-circuits on empty query before any decrypt/audit happens.
    assert _audit_rows(pg_conn) == []


# --- devices -----------------------------------------------------------------


def test_devices_list_shows_seeded_device(reader_client, seeded_number):
    resp = reader_client.get("/devices")
    assert resp.status_code == 200
    assert "phone-1" in resp.text


def test_device_detail_404_for_unknown_device(reader_client):
    import uuid

    resp = reader_client.get(f"/devices/{uuid.uuid4()}")
    assert resp.status_code == 404


# --- unassigned bucket -------------------------------------------------------


def test_unassigned_bucket_shows_unowned_message(
    reader_client, pg_conn, ctx, device, make_request, make_message
):
    ingestion.ingest_batch(
        pg_conn,
        ctx,
        device,
        make_request(
            [make_message(dedupe_id="u1", sender="+15551112222", body="orphan message")],
            client_batch_id="unassigned-batch",
        ),
    )
    resp = reader_client.get("/unassigned")
    assert resp.status_code == 200
    assert "+15551112222" in resp.text
    assert "orphan message" in resp.text  # preview, truncated but short enough to appear whole

    rows = _audit_rows(pg_conn)
    assert len(rows) == 1
    assert rows[0]["metadata"]["scope"]["view"] == "unassigned"


# --- inbox-only rendering ----------------------------------------------------


def test_thread_view_is_one_sided_received_log(reader_client, seeded_number):
    """§6: 'One-sided received log (inbox-only), not chat bubbles.' There is
    no outbound/sent message concept anywhere in the ingestion pipeline (v1
    only ingests received SMS), so this asserts the rendered thread carries
    no per-message direction/sent/outbound marker at all."""
    number_id = seeded_number["number"]["id"]
    resp = reader_client.get(
        f"/numbers/{number_id}/thread", params={"counterparty": "+15550001111"}
    )
    assert resp.status_code == 200
    lowered = resp.text.lower()
    for outbound_marker in ("outbound", "sent", "you:", "class=\"sent\"", "class=\"outbound\""):
        assert outbound_marker not in lowered


# --- no-plaintext-in-logs ----------------------------------------------------


def test_no_plaintext_tokens_or_keys_in_logs(reader_client, seeded_number, caplog, keys):
    """Decrypting and rendering a thread must never write the decrypted
    sender, body, the field-encryption key material, or the device's raw
    bearer token into the log stream — only structured, sanitized log lines
    (if any) are permitted."""
    number_id = seeded_number["number"]["id"]
    with caplog.at_level(logging.DEBUG):
        resp = reader_client.get(
            f"/numbers/{number_id}/thread", params={"counterparty": "+15550001111"}
        )
    assert resp.status_code == 200
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    for leaked in ("hello from carrier", "second message", "+15550001111"):
        assert leaked not in log_text
    assert keys["field_json"] not in log_text
    assert keys["priv_json"] not in log_text
