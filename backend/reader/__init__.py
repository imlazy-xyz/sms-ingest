"""Admin Reader UI — local-first, read-only SMS browsing app.

A separate ASGI app from the ingest service, reusing ``app.core`` and
``app.repositories``. This package owns the reader's routers, templates, and
read-side hardening (loopback binding, read-audit, auth seam).

Submodules in this package are independently importable so the integration
owner (`backend/reader/main.py`, not added here) can mount them:

- ``reader.binding``  — loopback-bind enforcement.
- ``reader.audit``    — read-audit hook; every decrypt-read records one
  sanitized ``audit_events`` row.
- ``reader.auth``     — operator-principal middleware/dependency; WebAuthn
  seam documented, not built.
"""

from __future__ import annotations
