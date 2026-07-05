"""Unit tests for HMAC dedupe canonicalization and IDs (no DB)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.core import dedupe

SECRET = "device-dedupe-secret"
WHEN = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_canonical_string_format():
    s = dedupe.canonical_string("inbox", "+15551230000", WHEN, "hello")
    assert s == (
        "v1\n"
        "direction=inbox\n"
        "sender=+15551230000\n"
        f"sms_received_at={dedupe.epoch_millis(WHEN)}\n"
        "body=hello\n"
    )


def test_epoch_millis_assumes_utc_for_naive():
    naive = datetime(2026, 7, 1, 12, 0, 0)
    assert dedupe.epoch_millis(naive) == dedupe.epoch_millis(WHEN)


def test_sender_normalization_trims_whitespace():
    assert dedupe.normalize_sender("  +1555  ") == "+1555"
    a = dedupe.compute_dedupe_id(SECRET, "inbox", "  +1555  ", WHEN, "hi")
    b = dedupe.compute_dedupe_id(SECRET, "inbox", "+1555", WHEN, "hi")
    assert a == b


def test_dedupe_id_is_stable_and_content_sensitive():
    a = dedupe.compute_dedupe_id(SECRET, "inbox", "+1555", WHEN, "hello")
    b = dedupe.compute_dedupe_id(SECRET, "inbox", "+1555", WHEN, "hello")
    assert a == b  # stable across retries
    different_body = dedupe.compute_dedupe_id(SECRET, "inbox", "+1555", WHEN, "hell0")
    assert a != different_body
    different_secret = dedupe.compute_dedupe_id("other", "inbox", "+1555", WHEN, "hello")
    assert a != different_secret
