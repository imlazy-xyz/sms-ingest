"""Device bearer tokens and dedupe secrets.

* Tokens/secrets are opaque, high-entropy (>=256-bit) random values, base64url.
* The raw token is emitted once in the QR payload and never stored server-side.
* Only a keyed hash (HMAC-SHA256 with ``TOKEN_HASH_PEPPER``) and a short,
  non-secret prefix are persisted; the pepper hardens the hash if the DB leaks.

Never log raw tokens, dedupe secrets, or the pepper.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

TOKEN_BYTES = 32  # 256 bits
PREFIX_LEN = 8


def _b64url_nopad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_token() -> str:
    return _b64url_nopad(secrets.token_bytes(TOKEN_BYTES))


def generate_dedupe_secret() -> str:
    return _b64url_nopad(secrets.token_bytes(TOKEN_BYTES))


def hash_token(raw_token: str, pepper: str) -> str:
    """Keyed hash stored in ``devices.token_hash``. Deterministic for lookup."""
    return hmac.new(
        pepper.encode("utf-8"), raw_token.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def token_prefix(raw_token: str) -> str:
    """Short, non-secret prefix for human lookup/debugging only."""
    return raw_token[:PREFIX_LEN]


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
