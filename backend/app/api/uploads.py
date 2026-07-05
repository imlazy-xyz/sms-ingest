"""Encrypted SMS batch upload route."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app import db
from app.context import AppContext
from app.core import auth
from app.models.api import NextSync, RejectedItem, UploadBatchRequest, UploadResponse
from app.repositories import devices
from app.services import ingestion

logger = logging.getLogger("sms_ingest.uploads")

router = APIRouter()


def get_app_context(request: Request) -> AppContext:
    app = request.app
    if getattr(app.state, "ctx", None) is None:
        app.state.ctx = AppContext.from_settings(app.state.settings)
    return app.state.ctx


@router.post("/v1/uploads/sms-batches", response_model=UploadResponse)
def upload_sms_batches(
    payload: UploadBatchRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> UploadResponse:
    ctx = get_app_context(request)
    settings = request.app.state.settings

    with db.connection(settings) as conn:
        try:
            device = auth.authenticate(conn, authorization, ctx.token_pepper)
        except auth.AuthError:
            # Do not echo the reason or the token; keep 401 generic.
            raise HTTPException(status_code=401, detail="unauthorized")

        devices.touch_last_seen(conn, device.id)

        try:
            result = ingestion.ingest_batch(conn, ctx, device, payload)
        except ingestion.BatchRejected as exc:
            raise HTTPException(
                status_code=400,
                detail={"status": "rejected", "reason": exc.reason},
            )

    return UploadResponse(
        status=result.status,
        server_batch_id=result.server_batch_id,
        accepted_count=result.accepted_count,
        duplicate_count=result.duplicate_count,
        rejected_count=result.rejected_count,
        rejected=[
            RejectedItem(client_message_id=r.client_message_id, reason=r.reason)
            for r in result.rejected
        ],
        next_sync=NextSync(),
    )
