"""Application configuration.

Secrets are loaded from the environment (or a local ``.env`` in dev). They are
optional at import time so that non-secret paths (e.g. the health check) and pure
unit tests can run without production key material. Accessors raise a clear error
when a required secret is missing at the point of use.

Never log the values of these settings.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Database
    database_url: str = ""

    # Tink HPKE keysets (JSON keyset material). Private is used to decrypt batches;
    # public is used to compute the key pin and to hand to Android out of band.
    tink_private_keyset_json: str | None = None
    tink_public_keyset_json: str | None = None
    server_key_id: str | None = None

    # Tink AEAD keyset (JSON) used to encrypt sensitive SMS fields before storage.
    field_encryption_key: str | None = None

    # Pepper (HMAC key) applied when hashing device bearer tokens.
    token_hash_pepper: str | None = None

    # Ingestion treats this as optional: when set, uploads are validated against it
    # (api_base_url_mismatch); when unset, that check is skipped. Provisioning
    # (cli/main.py create-device, rotate-token) treats it as required instead — a QR
    # payload with no API URL is useless, so those commands raise if it's unset. Set
    # it via env when running the CLI; the running Cloud Run service does not need it.
    api_base_url: str | None = None

    # Fallback retention window; the authoritative value lives in app_config.
    retention_days: int = 90

    def require(self, name: str) -> str:
        value = getattr(self, name)
        if not value:
            raise RuntimeError(
                f"Required setting '{name.upper()}' is not configured. "
                "Set it via environment or Cloud Run secrets."
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
