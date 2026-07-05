"""Retention cleanup tests (integration: require Postgres via pg_conn)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core import retention, tokens
from app.models.domain import Device
from app.repositories import devices
from app.services import ingestion


def _device(conn, keys):
    row = devices.insert(
        conn,
        label="phone",
        token_prefix=tokens.token_prefix("tok"),
        token_hash=tokens.hash_token("tok", keys["pepper"]),
    )
    return Device(id=row["id"], label="phone", status="active", token_prefix=row["token_prefix"])


def _ingest_one(pg_conn, ctx, device, make_request, make_message, *, dedupe_id, received_at):
    ingestion.ingest_batch(
        pg_conn,
        ctx,
        device,
        make_request(
            [make_message(dedupe_id=dedupe_id, sms_received_at=received_at)],
            client_batch_id=dedupe_id,
        ),
    )


def test_cleanup_deletes_only_expired(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    now = datetime.now(timezone.utc)
    # retention_days defaults to 90; one message is 200 days old (expired),
    # the other is recent (not expired).
    _ingest_one(
        pg_conn, ctx, device, make_request, make_message,
        dedupe_id="old", received_at=(now - timedelta(days=200)).isoformat(),
    )
    _ingest_one(
        pg_conn, ctx, device, make_request, make_message,
        dedupe_id="new", received_at=(now - timedelta(days=1)).isoformat(),
    )
    assert pg_conn.execute("select count(*) n from sms_records").fetchone()["n"] == 2

    deleted = retention.run_cleanup(pg_conn, now)
    assert deleted == 1

    remaining = pg_conn.execute("select dedupe_id from sms_records").fetchall()
    assert [r["dedupe_id"] for r in remaining] == ["new"]

    counts = pg_conn.execute(
        "select metadata from audit_events where event_type='retention.deleted' order by occurred_at desc limit 1"
    ).fetchone()
    assert counts["metadata"]["deleted_count"] == 1


def test_cleanup_is_idempotent(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    now = datetime.now(timezone.utc)
    _ingest_one(
        pg_conn, ctx, device, make_request, make_message,
        dedupe_id="old", received_at=(now - timedelta(days=200)).isoformat(),
    )
    assert retention.run_cleanup(pg_conn, now) == 1
    assert retention.run_cleanup(pg_conn, now) == 0  # nothing left; still safe
    # Both runs recorded an audit event (count 1 then 0).
    events = pg_conn.execute(
        "select count(*) n from audit_events where event_type='retention.deleted'"
    ).fetchone()["n"]
    assert events == 2
