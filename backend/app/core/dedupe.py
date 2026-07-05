"""HMAC dedupe fingerprints.

The device computes ``dedupe_id`` from a canonical string using its
``device_dedupe_secret`` and sends it inside the encrypted batch. The backend
enforces uniqueness on ``(device_id, dedupe_id)``; it does not need the secret at
ingest time. This module defines the canonical form so backend tests (and any
future validation tooling) stay byte-compatible with the Android implementation.

Canonical string (exact, newline-separated, trailing newline included):

    v1\\n
    direction=<direction>\\n
    sender=<normalized_sender>\\n
    sms_received_at=<epoch_millis>\\n
    body=<exact_body>\\n

Dedupe ID: ``base64url_nopad(HMAC-SHA256(device_dedupe_secret, canonical))``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timezone


def normalize_sender(sender: str) -> str:
    """Trim surrounding whitespace only. Digits/format are preserved so no
    information is lost; the Android side applies the same normalization."""
    return sender.strip()


def epoch_millis(received_at: datetime) -> int:
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)
    return int(received_at.timestamp() * 1000)


def canonical_string(
    direction: str, sender: str, sms_received_at: datetime, body: str
) -> str:
    return (
        "v1\n"
        f"direction={direction}\n"
        f"sender={normalize_sender(sender)}\n"
        f"sms_received_at={epoch_millis(sms_received_at)}\n"
        f"body={body}\n"
    )


def compute_dedupe_id(
    dedupe_secret: str,
    direction: str,
    sender: str,
    sms_received_at: datetime,
    body: str,
) -> str:
    canonical = canonical_string(direction, sender, sms_received_at, body)
    digest = hmac.new(
        dedupe_secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
