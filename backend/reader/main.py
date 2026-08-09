"""Reader ASGI application factory.

Mounts R's router (``reader.routers``) and A's operator-auth middleware
(``reader.auth.OperatorAuthMiddleware``). Loopback-bind enforcement
(``reader.binding``) is applied by the entrypoint that calls uvicorn — see
``reader/scripts/reader-up.sh`` and ``reader.binding.resolve_bind_host`` —
not here; this factory only assembles the ASGI app, it does not bind sockets.

Serves ``reader/static/`` (vendored htmx) at ``/static``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from reader.auth import OperatorAuthMiddleware
from reader.routers import router

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    app = FastAPI(title="SMS Ingest Admin Reader")
    app.state.settings = settings or get_settings()
    app.state.ctx = None

    app.add_middleware(OperatorAuthMiddleware)
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


app = create_app()
