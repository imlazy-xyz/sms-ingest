"""Health check route (no DB dependency, cheap)."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.models.api import HealthResponse

router = APIRouter()


@router.get("/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(version=__version__)
