"""Field-level encryption for sensitive SMS columns (Tink AEAD, AES-256-GCM).

``FIELD_ENCRYPTION_KEY`` holds a Tink AEAD keyset (JSON). Each field is encrypted
with an associated-data label (e.g. ``sms:body``) for domain separation, so a
ciphertext produced for one field cannot be decrypted as another. Stored as
``bytea``; never store or log plaintext.
"""

from __future__ import annotations

import tink
from tink import aead, cleartext_keyset_handle

from app.core.crypto import CryptoError

_REGISTERED = False


def _ensure_registered() -> None:
    global _REGISTERED
    if not _REGISTERED:
        aead.register()
        _REGISTERED = True


def load_field_aead(keyset_json: str) -> aead.Aead:
    _ensure_registered()
    try:
        handle = cleartext_keyset_handle.read(tink.JsonKeysetReader(keyset_json))
        return handle.primitive(aead.Aead)
    except tink.TinkError as exc:  # pragma: no cover - config error path
        raise CryptoError("invalid Tink field-encryption keyset") from exc


def _ad(field: str) -> bytes:
    return f"sms:{field}".encode("utf-8")


def encrypt_field(field_aead: aead.Aead, field: str, plaintext: str | None) -> bytes | None:
    if plaintext is None:
        return None
    return field_aead.encrypt(plaintext.encode("utf-8"), _ad(field))


def decrypt_field(field_aead: aead.Aead, field: str, ciphertext: bytes | None) -> str | None:
    if ciphertext is None:
        return None
    try:
        return field_aead.decrypt(bytes(ciphertext), _ad(field)).decode("utf-8")
    except tink.TinkError as exc:
        raise CryptoError("field decryption failed") from exc
