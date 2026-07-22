"""FastAPI application factory.

Crypto primitives are loaded lazily on the first request that needs them (see
``app.context.get_app_context``) so the app can start and serve health checks
even before all secrets are wired. Logging is minimal and never includes SMS
plaintext, tokens, or key material.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app import __version__
from app.api import health, public_key, uploads
from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    app = FastAPI(title="SMS Ingest API", version=__version__)
    app.state.settings = settings or get_settings()
    app.state.ctx = None

    app.include_router(health.router)
    app.include_router(public_key.router)
    app.include_router(uploads.router)
    return app


app = create_app()
