"""Public keyset route: lets a provisioned device fetch the backend's Tink
public keyset and verify it against the QR-pinned ``server_key_pin`` before
trusting it for encryption (key-pinning pattern: pin travels out of band via
the QR, the key itself travels in-band over this endpoint).

Unauthenticated: the keyset is public material, and the device must be able
to fetch it before it has anything else to prove trust with.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.context import get_app_context
from app.models.api import PublicKeyResponse

router = APIRouter()


@router.get("/v1/public-key", response_model=PublicKeyResponse)
def public_key(request: Request) -> PublicKeyResponse:
    ctx = get_app_context(request)
    return PublicKeyResponse(
        scheme=ctx.expected_scheme,
        server_key_id=ctx.server_key_id,
        server_key_pin=ctx.server_key_pin,
        public_keyset_json=ctx.public_keyset_json,
    )
