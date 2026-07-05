"""Unit tests for batch transport crypto and field encryption (no DB)."""

from __future__ import annotations

import base64
import json

import pytest

from app.core import crypto, field_crypto


def _encrypt(keys, plaintext: bytes, context_info: bytes) -> str:
    ct = keys["encrypt"].encrypt(plaintext, context_info)
    return base64.urlsafe_b64encode(ct).rstrip(b"=").decode("ascii")


def test_pin_is_deterministic(keys):
    assert crypto.compute_key_pin(keys["pub_json"]) == keys["pin"]
    assert crypto.compute_key_pin(keys["pub_json"]) == crypto.compute_key_pin(keys["pub_json"])


def test_hpke_roundtrip_with_context(keys):
    dec = crypto.load_hybrid_decrypt(keys["priv_json"])
    ci = crypto.canonical_context_info({"payload_type": "sms_batch", "version": 1})
    ct = _encrypt(keys, b'{"messages":[]}', ci)
    assert crypto.decrypt_batch(dec, ct, ci) == b'{"messages":[]}'


def test_context_info_binding_rejects_tamper(keys):
    dec = crypto.load_hybrid_decrypt(keys["priv_json"])
    ci = crypto.canonical_context_info({"payload_type": "sms_batch"})
    ct = _encrypt(keys, b"secret", ci)
    other = crypto.canonical_context_info({"payload_type": "sms_batch", "x": 1})
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt_batch(dec, ct, other)


def test_malformed_ciphertext_rejected(keys):
    dec = crypto.load_hybrid_decrypt(keys["priv_json"])
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt_batch(dec, "AAAA", b"ctx")  # valid base64, invalid HPKE


def test_canonical_context_info_is_order_independent():
    a = crypto.canonical_context_info({"b": 2, "a": 1})
    b = crypto.canonical_context_info({"a": 1, "b": 2})
    assert a == b == json.dumps({"a": 1, "b": 2}, separators=(",", ":")).encode()


def test_field_crypto_roundtrip_and_domain_separation(keys):
    a = field_crypto.load_field_aead(keys["field_json"])
    ct = field_crypto.encrypt_field(a, "body", "hi there")
    assert isinstance(ct, bytes) and ct != b"hi there"
    assert field_crypto.decrypt_field(a, "body", ct) == "hi there"
    # Ciphertext for one field must not decrypt as another (AD mismatch).
    with pytest.raises(crypto.CryptoError):
        field_crypto.decrypt_field(a, "sender", ct)


def test_field_crypto_handles_none(keys):
    a = field_crypto.load_field_aead(keys["field_json"])
    assert field_crypto.encrypt_field(a, "sim_info", None) is None
    assert field_crypto.decrypt_field(a, "sim_info", None) is None
