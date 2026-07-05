"""Device bearer-token authentication.

Tokens are verified before any payload is decrypted. The presented token is
hashed (keyed with the pepper) and matched against ``devices.token_hash``.
Missing/invalid/revoked tokens are rejected. Never log the Authorization header.
"""

from __future__ import annotations

import psycopg

from app.core import tokens
from app.models.domain import Device
from app.repositories import devices


class AuthError(Exception):
    """Raised when a device token is missing, malformed, unknown, or revoked."""


def parse_bearer(authorization: str | None) -> str:
    if not authorization:
        raise AuthError("missing Authorization header")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise AuthError("malformed Authorization header")
    return parts[1].strip()


def authenticate(
    conn: psycopg.Connection, authorization: str | None, pepper: str
) -> Device:
    raw_token = parse_bearer(authorization)
    token_hash = tokens.hash_token(raw_token, pepper)
    row = devices.get_by_token_hash(conn, token_hash)
    if row is None:
        raise AuthError("unknown device token")
    if row["status"] != "active" or row["revoked_at"] is not None:
        raise AuthError("revoked device token")
    return Device(
        id=row["id"],
        label=row["label"],
        status=row["status"],
        token_prefix=row["token_prefix"],
        revoked_at=row["revoked_at"],
    )
