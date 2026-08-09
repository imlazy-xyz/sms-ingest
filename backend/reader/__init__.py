"""Admin Reader UI — local-first, read-only SMS browsing app (FastAPI + Jinja + htmx).

A separate ASGI app from the ingest service, reusing ``app.core`` and
``app.repositories``. This package owns the reader's routers, Jinja templates,
decrypt/service layer, and read-side hardening (loopback binding, read-audit,
auth seam). ASGI app assembly (``main.py``) is owned by the integration agent
and lives outside this package.

Submodules in this package are independently importable so the integration
owner can mount them:

- ``reader.binding``  — loopback-bind enforcement.
- ``reader.audit``    — read-audit hook; every decrypt-read records one
  sanitized ``audit_events`` row.
- ``reader.auth``     — operator-principal middleware/dependency; WebAuthn
  seam documented, not built.
- ``reader.service``  — decrypt/workflow layer. Decryption happens
  server-side only; the browser receives only rendered HTML. Never log or
  print SMS plaintext, decrypted payloads, tokens, or key material from this
  package (see ``reader.service`` module docstring for the two decrypt
  scopes and their cost boundaries).
- ``reader.routers``  — the mountable ``APIRouter`` with the §6 screens.
"""

from __future__ import annotations
