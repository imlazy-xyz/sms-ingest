"""Health endpoint smoke test (no DB required)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import __version__
from app.main import create_app


def test_health_ok(settings):
    with TestClient(create_app(settings)) as client:
        resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": __version__}
