"""Runtime context: crypto primitives and config loaded once at startup.

Built from :class:`app.config.Settings`. Keysets are parsed a single time and the
primitives are reused across requests. Stored on ``app.state`` and passed into
services so request handlers never touch raw keyset material.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from tink import aead, hybrid

from app.config import Settings, get_settings
from app.core import crypto, field_crypto


@dataclass
class AppContext:
    hybrid_decrypt: hybrid.HybridDecrypt
    field_aead: aead.Aead
    token_pepper: str
    server_key_id: str
    server_key_pin: str
    public_keyset_json: str
    api_base_url: str | None
    retention_days_default: int
    expected_scheme: str = crypto.SCHEME

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "AppContext":
        settings = settings or get_settings()
        public_keyset = settings.require("tink_public_keyset_json")
        return cls(
            hybrid_decrypt=crypto.load_hybrid_decrypt(
                settings.require("tink_private_keyset_json")
            ),
            field_aead=field_crypto.load_field_aead(
                settings.require("field_encryption_key")
            ),
            token_pepper=settings.require("token_hash_pepper"),
            server_key_id=settings.require("server_key_id"),
            server_key_pin=crypto.compute_key_pin(public_keyset),
            public_keyset_json=public_keyset,
            api_base_url=settings.api_base_url,
            retention_days_default=settings.retention_days,
        )


def get_app_context(request: Request) -> AppContext:
    """Lazily build and cache the app's :class:`AppContext` on ``app.state``."""
    app = request.app
    if getattr(app.state, "ctx", None) is None:
        app.state.ctx = AppContext.from_settings(app.state.settings)
    return app.state.ctx
