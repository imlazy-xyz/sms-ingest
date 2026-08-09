"""Reader operator-principal auth.

v1 auth boundary is **loopback binding** (see ``reader.binding``), not
credential-based auth. This module exists so the reader's ``main.py``
and the reader's routes have a stable, documented seam to call — today it just
establishes an "operator" principal (trusted because the process is only
reachable on loopback); it does not verify a credential.

WebAuthn/passkey seam (do NOT build in v1):
    When a domain exists and passkey auth is built, it slots in here:
    replace :func:`get_operator` (or add a FastAPI dependency alongside it)
    with one that verifies a WebAuthn session cookie and raises
    ``OperatorAuthError`` on failure, instead of unconditionally returning
    the trusted-by-loopback principal. The public interface
    (``get_operator`` returning an ``Operator`` with ``.actor_id``) should
    stay stable so the reader's routes and the read-audit call site don't need to
    change — only the verification behind it does.

Usage:
    - As ASGI middleware: mount :class:`OperatorAuthMiddleware` in
      ``main.py`` to stamp ``request.state.operator`` on every request.
    - As a FastAPI dependency: use :func:`get_operator` directly in a route
      signature (``operator: Operator = Depends(get_operator)``) when a
      route needs the principal without relying on middleware ordering.

Either way, the resulting ``actor_id`` is what the reader's read path should pass to
``reader.audit.record_read(..., actor_id=operator.actor_id, ...)``.
"""

from __future__ import annotations

from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

#: v1 has exactly one operator (a single-operator tool). This id is
#: what gets recorded as `actor_id` on every read-audit row. Not a secret.
DEFAULT_OPERATOR_ID = "operator"


class OperatorAuthError(Exception):
    """Raised when the operator principal cannot be established.

    Unused in v1 (loopback binding is the boundary, not credential
    verification — see module docstring). Reserved for the WebAuthn seam so
    callers can already handle this exception type before it's ever raised.
    """


@dataclass(frozen=True)
class Operator:
    """The authenticated operator principal for a request.

    ``actor_id`` is the value the reader's read path should pass to
    ``reader.audit.record_read(actor_id=...)``.
    """

    actor_id: str


def get_operator(request: Request) -> Operator:
    """FastAPI dependency: resolve the operator principal for this request.

    v1: unconditionally returns the single trusted operator — trust is
    established by the process only being reachable on loopback
    (``reader.binding.enforce_loopback``), not by a credential check here.
    Post-passkey, replace this body with WebAuthn session verification (see
    module docstring); keep the ``Operator`` return type stable.
    """
    return Operator(actor_id=DEFAULT_OPERATOR_ID)


class OperatorAuthMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that stamps ``request.state.operator`` on every request.

    v1 behavior mirrors :func:`get_operator`: it does not reject any
    request (loopback binding is the enforcement point, applied at bind
    time, before this middleware ever runs). This middleware exists so
    routes can read ``request.state.operator`` without each one declaring
    the ``get_operator`` dependency individually, and so the WebAuthn seam
    has one place (this class) to add request rejection later.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        request.state.operator = Operator(actor_id=DEFAULT_OPERATOR_ID)
        return await call_next(request)
