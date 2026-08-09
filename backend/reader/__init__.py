"""Read-only admin reader UI (FastAPI + Jinja + htmx).

Server-rendered screens over the ingest backend's shared ``app.core`` /
``app.repositories`` code. This package owns routers, Jinja templates, and a
decrypt/service layer; the ASGI app assembly (``main.py``) is owned by the
integration agent and lives outside this package.

Decryption happens server-side only (see ``reader.service``); the browser
receives only rendered HTML. Never log or print SMS plaintext, decrypted
payloads, tokens, or key material from this package (see ``reader.service``
module docstring for the two decrypt scopes and their cost boundaries).
"""

from __future__ import annotations
