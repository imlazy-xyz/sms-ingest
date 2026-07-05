"""Batch transport crypto: Google Tink HPKE hybrid decryption + key pinning.

Wire contract (must match the Android encrypt side):

* Key type: ``DHKEM_X25519_HKDF_SHA256_HKDF_SHA256_AES_256_GCM``.
* Scheme label: ``tink-hpke-x25519-aes256gcm-v1``.
* ``ciphertext`` is Tink's HPKE wire format, base64url-encoded (no padding).
* HPKE ``context_info`` is the canonical JSON of the request's ``context_info``
  object: ``json.dumps(obj, sort_keys=True, separators=(",", ":"))`` as UTF-8.
  Both sides derive the same bytes regardless of wire key order, and any
  tampering with the bound metadata makes decryption fail.
* The key pin is ``base64url_nopad(SHA-256(binary-serialized public keyset))``.

Never log ciphertext, plaintext, or keyset material.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from typing import Any

import tink
from tink import cleartext_keyset_handle, hybrid

SCHEME = "tink-hpke-x25519-aes256gcm-v1"

_REGISTERED = False


def _ensure_registered() -> None:
    global _REGISTERED
    if not _REGISTERED:
        hybrid.register()
        _REGISTERED = True


def _b64url_nopad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


class CryptoError(Exception):
    """Raised when keyset loading, pin calculation, or decryption fails."""


def load_hybrid_decrypt(private_keyset_json: str) -> hybrid.HybridDecrypt:
    _ensure_registered()
    try:
        handle = cleartext_keyset_handle.read(
            tink.JsonKeysetReader(private_keyset_json)
        )
        return handle.primitive(hybrid.HybridDecrypt)
    except tink.TinkError as exc:  # pragma: no cover - config error path
        raise CryptoError("invalid Tink private keyset") from exc


def _public_keyset_binary(public_keyset_json: str) -> bytes:
    _ensure_registered()
    handle = cleartext_keyset_handle.read(tink.JsonKeysetReader(public_keyset_json))
    stream = io.BytesIO()
    cleartext_keyset_handle.write(tink.BinaryKeysetWriter(stream), handle)
    return stream.getvalue()


def compute_key_pin(public_keyset_json: str) -> str:
    """Deterministic fingerprint of the backend public keyset used for pinning."""
    try:
        digest = hashlib.sha256(_public_keyset_binary(public_keyset_json)).digest()
    except tink.TinkError as exc:  # pragma: no cover - config error path
        raise CryptoError("invalid Tink public keyset") from exc
    return _b64url_nopad(digest)


def canonical_context_info(context_info: dict[str, Any]) -> bytes:
    """Canonical byte encoding of the bound public metadata (sorted, compact)."""
    return json.dumps(
        context_info, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def decrypt_batch(
    hybrid_decrypt: hybrid.HybridDecrypt,
    ciphertext_b64url: str,
    context_info: bytes,
) -> bytes:
    """Decrypt a base64url HPKE ciphertext bound to ``context_info``.

    Raises :class:`CryptoError` for malformed base64, malformed ciphertext, or a
    context-info mismatch (a single generic error avoids an oracle).
    """
    try:
        ciphertext = _b64url_decode(ciphertext_b64url)
    except (ValueError, TypeError) as exc:
        raise CryptoError("malformed ciphertext encoding") from exc
    try:
        return hybrid_decrypt.decrypt(ciphertext, context_info)
    except tink.TinkError as exc:
        raise CryptoError("batch decryption failed") from exc
