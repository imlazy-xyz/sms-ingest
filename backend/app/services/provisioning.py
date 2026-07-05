"""Device provisioning workflows used by the admin CLI.

Creates/revokes/rotates device credentials and builds the one-time QR payload.
The raw token and dedupe secret are emitted only in the returned payload and are
never persisted in plaintext (only ``token_hash`` and an optional encrypted
dedupe secret are stored). Callers must not log the payload.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import psycopg

from app.config import Settings
from app.core import audit, crypto, field_crypto, tokens
from app.repositories import devices

_DEDUPE_FIELD = "dedupe_secret"


def build_qr_payload(
    settings: Settings, device_id: str, raw_token: str, dedupe_secret: str
) -> dict[str, Any]:
    return {
        "v": 1,
        "api_base_url": settings.require("api_base_url"),
        "device_id": device_id,
        "device_token": raw_token,
        "device_dedupe_secret": dedupe_secret,
        "server_key_id": settings.require("server_key_id"),
        "server_key_pin": crypto.compute_key_pin(
            settings.require("tink_public_keyset_json")
        ),
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }


def create_device(
    conn: psycopg.Connection, settings: Settings, label: str
) -> dict[str, Any]:
    raw_token = tokens.generate_token()
    dedupe_secret = tokens.generate_dedupe_secret()
    token_hash = tokens.hash_token(raw_token, settings.require("token_hash_pepper"))
    prefix = tokens.token_prefix(raw_token)

    field_aead = field_crypto.load_field_aead(settings.require("field_encryption_key"))
    dedupe_secret_enc = field_crypto.encrypt_field(field_aead, _DEDUPE_FIELD, dedupe_secret)

    with conn.transaction():
        row = devices.insert(
            conn,
            label=label,
            token_prefix=prefix,
            token_hash=token_hash,
            dedupe_secret_enc=dedupe_secret_enc,
        )
        audit.record(
            conn,
            audit.DEVICE_CREATED,
            actor_type=audit.ACTOR_ADMIN,
            device_id=row["id"],
            metadata={"label": label, "token_prefix": prefix},
        )

    return build_qr_payload(settings, str(row["id"]), raw_token, dedupe_secret)


def revoke_device(conn: psycopg.Connection, device_id: UUID | str) -> bool:
    with conn.transaction():
        changed = devices.revoke(conn, device_id) > 0
        if changed:
            audit.record(
                conn,
                audit.DEVICE_REVOKED,
                actor_type=audit.ACTOR_ADMIN,
                device_id=device_id,
            )
    return changed


def rotate_token(
    conn: psycopg.Connection, settings: Settings, device_id: UUID | str
) -> dict[str, Any] | None:
    """Issue a new bearer token while keeping the dedupe secret stable, and return
    a fresh QR payload. Returns ``None`` if the device does not exist. Requires the
    dedupe secret to have been stored encrypted at creation time."""
    existing = devices.get_by_id(conn, device_id)
    if existing is None:
        return None

    row = conn.execute(
        "select dedupe_secret_enc from devices where id = %s", (device_id,)
    ).fetchone()
    if row is None or row["dedupe_secret_enc"] is None:
        raise ValueError(
            "device has no stored dedupe secret; cannot reissue QR on rotation"
        )
    field_aead = field_crypto.load_field_aead(settings.require("field_encryption_key"))
    dedupe_secret = field_crypto.decrypt_field(
        field_aead, _DEDUPE_FIELD, row["dedupe_secret_enc"]
    )

    raw_token = tokens.generate_token()
    token_hash = tokens.hash_token(raw_token, settings.require("token_hash_pepper"))
    prefix = tokens.token_prefix(raw_token)

    with conn.transaction():
        devices.rotate_token(
            conn, device_id, token_prefix=prefix, token_hash=token_hash
        )
        audit.record(
            conn,
            audit.DEVICE_TOKEN_ROTATED,
            actor_type=audit.ACTOR_ADMIN,
            device_id=device_id,
            metadata={"token_prefix": prefix},
        )

    return build_qr_payload(settings, str(device_id), raw_token, dedupe_secret)
