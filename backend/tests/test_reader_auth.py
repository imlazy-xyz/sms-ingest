"""Reader operator-auth seam tests (unit; no DB required)."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from reader.auth import DEFAULT_OPERATOR_ID, Operator, OperatorAuthMiddleware, get_operator


def test_operator_auth_middleware_stamps_request_state():
    """Middleware path: main.py mounts it, routes read request.state.operator."""
    app = FastAPI()
    app.add_middleware(OperatorAuthMiddleware)

    @app.get("/whoami")
    def whoami(request: Request):
        return {"actor_id": request.state.operator.actor_id}

    client = TestClient(app)
    resp = client.get("/whoami")
    assert resp.status_code == 200
    assert resp.json()["actor_id"] == DEFAULT_OPERATOR_ID


def test_get_operator_works_as_fastapi_dependency():
    """Dependency path: a route can take the principal without middleware."""
    app = FastAPI()

    @app.get("/whoami")
    def whoami(operator: Operator = Depends(get_operator)):
        return {"actor_id": operator.actor_id}

    client = TestClient(app)
    resp = client.get("/whoami")
    assert resp.status_code == 200
    assert resp.json()["actor_id"] == DEFAULT_OPERATOR_ID


def test_operator_is_frozen_dataclass():
    """actor_id must not be mutable after the principal is established."""
    import dataclasses

    op = Operator(actor_id="x")
    try:
        op.actor_id = "y"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:  # pragma: no cover
        raise AssertionError("Operator should be immutable")
