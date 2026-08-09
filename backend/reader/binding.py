"""Loopback-bind enforcement — the v1 auth boundary for the reader.

The reader has no passkey/WebAuthn auth in v1 (see ``reader.auth`` for the
documented seam). Instead, the reader refuses to serve on a non-loopback
interface by default. This module is a **validator**, not a socket binder:
it does not call ``uvicorn.run`` itself. The reader's ``main.py`` entrypoint
(or the Podman bring-up script) is expected to call :func:`resolve_bind_host`
to get the host string to pass to the ASGI server, or :func:`enforce_loopback`
to validate a host it already has.

Passkey/WebAuthn seam: once a domain exists and passkey auth lands (which
is sequenced after loopback-only v1), the escape hatch here
(``allow_non_loopback``) is where a caller opts out of the loopback
restriction for a real, authenticated deployment. Do not wire that up until
passkey auth exists — v1 must not expose the reader off loopback.
"""

from __future__ import annotations

import ipaddress

#: Hostnames treated as loopback without a DNS/IP lookup. `localhost` is
#: conventionally loopback; we don't resolve it (no network I/O in a
#: validator) but accept it by name.
_LOOPBACK_HOSTNAMES = {"localhost"}

#: Default bind host when the caller hasn't specified one.
DEFAULT_HOST = "127.0.0.1"

#: Environment variable an operator can set to explicitly opt out of the
#: loopback restriction. Not wired to anything else; reserved for the
#: eventual post-passkey cloud path. Absent/unset = restricted.
ALLOW_NON_LOOPBACK_ENV = "READER_ALLOW_NON_LOOPBACK"


class NonLoopbackBindError(ValueError):
    """Raised when a bind host is not loopback and no explicit opt-out was given."""


def is_loopback_host(host: str) -> bool:
    """Return True if ``host`` is a loopback address or the ``localhost`` name."""
    host = host.strip()
    if host.lower() in _LOOPBACK_HOSTNAMES:
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_loopback


def enforce_loopback(host: str, *, allow_non_loopback: bool = False) -> str:
    """Validate that ``host`` is safe to bind to under the v1 auth model.

    Returns ``host`` unchanged if it is loopback (127.0.0.1, ::1,
    ``localhost``) or if ``allow_non_loopback`` is explicitly True. Raises
    :class:`NonLoopbackBindError` otherwise. Callers (the reader's
    ``main.py`` / the bring-up script) must not silently swallow this exception —
    a caught-and-ignored error here defeats the entire v1 auth boundary.
    """
    if allow_non_loopback:
        return host
    if not is_loopback_host(host):
        raise NonLoopbackBindError(
            f"refusing to bind reader to non-loopback host {host!r}; "
            "the v1 auth boundary is loopback-only. Pass "
            "allow_non_loopback=True only for an already-authenticated "
            "deployment (post-passkey, not v1)."
        )
    return host


def resolve_bind_host(
    requested_host: str | None = None, *, allow_non_loopback: bool = False
) -> str:
    """Resolve the host the reader ASGI server should bind to.

    ``requested_host`` defaults to :data:`DEFAULT_HOST` (127.0.0.1) when not
    given. The result is always validated through :func:`enforce_loopback`.
    """
    host = requested_host if requested_host else DEFAULT_HOST
    return enforce_loopback(host, allow_non_loopback=allow_non_loopback)
