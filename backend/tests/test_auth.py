"""Auth tests: bearer parsing + token hashing (unit) and device lookup (integration)."""

from __future__ import annotations

import pytest

from app.core import auth, tokens
from app.repositories import devices
from app.services import provisioning

# --- Unit: bearer parsing ---------------------------------------------------


def test_parse_bearer_ok():
    assert auth.parse_bearer("Bearer abc.def") == "abc.def"
    assert auth.parse_bearer("bearer abc") == "abc"


@pytest.mark.parametrize("header", [None, "", "abc", "Basic abc", "Bearer", "Bearer   "])
def test_parse_bearer_rejects(header):
    with pytest.raises(auth.AuthError):
        auth.parse_bearer(header)


# --- Unit: token hashing ----------------------------------------------------


def test_hash_token_is_deterministic_and_pepper_sensitive():
    assert tokens.hash_token("raw", "pep") == tokens.hash_token("raw", "pep")
    assert tokens.hash_token("raw", "pep") != tokens.hash_token("raw", "other")
    assert tokens.hash_token("raw", "pep") != tokens.hash_token("raw2", "pep")


def test_token_prefix_length():
    raw = tokens.generate_token()
    assert tokens.token_prefix(raw) == raw[:8]
    assert len(tokens.generate_token()) >= 40  # 256-bit base64url


# --- Integration: device authentication -------------------------------------


def _make_device(conn, pepper, raw_token, label="phone"):
    return devices.insert(
        conn,
        label=label,
        token_prefix=tokens.token_prefix(raw_token),
        token_hash=tokens.hash_token(raw_token, pepper),
    )


def test_authenticate_accepts_active_device(pg_conn, keys):
    _make_device(pg_conn, keys["pepper"], "raw-token-1")
    device = auth.authenticate(pg_conn, "Bearer raw-token-1", keys["pepper"])
    assert device.status == "active"


def test_authenticate_rejects_unknown_token(pg_conn, keys):
    with pytest.raises(auth.AuthError):
        auth.authenticate(pg_conn, "Bearer nope", keys["pepper"])


def test_authenticate_rejects_revoked_device(pg_conn, keys):
    row = _make_device(pg_conn, keys["pepper"], "raw-token-2")
    devices.revoke(pg_conn, row["id"])
    with pytest.raises(auth.AuthError):
        auth.authenticate(pg_conn, "Bearer raw-token-2", keys["pepper"])


def test_authenticate_rejects_missing_header(pg_conn, keys):
    with pytest.raises(auth.AuthError):
        auth.authenticate(pg_conn, None, keys["pepper"])
