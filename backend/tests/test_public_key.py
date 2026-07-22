"""Public keyset endpoint: lets a device fetch and verify the backend's
Tink public keyset against the QR-pinned server_key_pin (no DB required)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core import crypto
from app.main import create_app


def test_public_key_matches_pin_and_keyset(settings, keys):
    with TestClient(create_app(settings)) as client:
        resp = client.get("/v1/public-key")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scheme"] == crypto.SCHEME
    assert body["server_key_id"] == keys["key_id"]
    assert body["server_key_pin"] == keys["pin"]
    assert body["public_keyset_json"] == keys["pub_json"]
    assert crypto.compute_key_pin(body["public_keyset_json"]) == body["server_key_pin"]
