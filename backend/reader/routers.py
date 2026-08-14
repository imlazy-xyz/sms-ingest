"""HTTP routes for the admin reader UI.

Contributes a mountable :data:`router` (an :class:`~fastapi.APIRouter`) — the
reader's ``main.py`` (owned by the integration workstream, not this module)
mounts it alongside the auth middleware. This module owns no app assembly.

Screens (per plan §6, information architecture User -> Number -> Conversations
-> Messages):

* ``GET /search``                         -- htmx partial: structural
  (cleartext-only) jump-to a user/number by name or e164/label
* ``GET /users``                          -- users list
* ``GET /users/{user_id}``                -- user detail (their numbers)
* ``GET /numbers/{number_id}``            -- reading view: conversation list
  (left pane) + an empty right pane, filled in via htmx
* ``GET /numbers/{number_id}/thread``     -- htmx partial: one thread window
* ``GET /numbers/{number_id}/search``     -- htmx partial: scoped search
  results within this number's window
* ``GET /devices``                        -- technical devices view
* ``GET /devices/{device_id}``            -- device detail
* ``GET /unassigned``                     -- unassigned bucket

Every route that decrypts anything calls :func:`_audit_read` exactly once,
after decryption, before returning the response — see that helper for why the
translation from :class:`reader.service.ReadScope` to the audit call is not a
passthrough.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.templating import Jinja2Templates

from app import db
from app.context import get_app_context
from app.repositories import numbers as numbers_repo
from app.repositories import users as users_repo
from reader import service
from reader.audit import record_read
from reader.auth import Operator, get_operator

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

_RECENT_WINDOW = timedelta(hours=24)


def _is_recent(value: datetime | None) -> bool:
    """Purely presentational (v2 §5): highlight a timestamp already on the
    page, no new query or decrypt. Naive datetimes are treated as UTC rather
    than compared against an aware `now` and raising."""
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - value < _RECENT_WINDOW


templates.env.globals["is_recent"] = _is_recent


# --- audit translation -------------------------------------------------
#
# reader.audit.record_read's `scope` accepts only a small allowlist of keys
# (number_id/user_id/device_id/view/date_from/date_to/search_applied) and a
# separate `message_count` int. reader.service.ReadScope carries more detail
# (rows_scanned, senders_decrypted, bodies_decrypted) for internal/future use
# that record_read's allowlist deliberately rejects. Passing
# `ReadScope.as_metadata()` straight through would raise ValueError on the
# first call (unknown keys `rows_scanned` etc.) -- this helper picks only the
# allowed identifying fields and derives message_count from bodies_decrypted
# (the count of *messages* actually rendered, not rows merely scanned).


def _audit_read(
    conn: Any,
    operator: Operator,
    scope: service.ReadScope,
    *,
    search_applied: bool | None = None,
) -> None:
    audit_scope: dict[str, Any] = {"view": scope.view}
    if scope.number_id is not None:
        audit_scope["number_id"] = scope.number_id
    if scope.user_id is not None:
        audit_scope["user_id"] = scope.user_id
    if scope.device_id is not None:
        audit_scope["device_id"] = scope.device_id
    if search_applied is not None:
        audit_scope["search_applied"] = search_applied
    record_read(
        conn,
        actor_id=operator.actor_id,
        scope=audit_scope,
        message_count=scope.bodies_decrypted,
        reason=scope.view,
    )


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found")


def _is_htmx(request: Request) -> bool:
    """True for a sort/filter link's htmx swap request, false for the
    initial full-page load -- lets one route serve both the full page and
    just the table partial it swaps (plan §4.3)."""
    return request.headers.get("hx-request") == "true"


# --- users ---------------------------------------------------------------

_USER_SORTS = {
    "name": lambda rows: sorted(rows, key=lambda r: r["user"]["display_name"].casefold()),
    "messages": lambda rows: sorted(rows, key=lambda r: r["message_count"], reverse=True),
    # "activity" needs no re-sort: service.users_overview already returns
    # most-recent-first (plan §4.1).
    "activity": lambda rows: rows,
}


@router.get("/users")
def users_list(request: Request, sort: str = "activity") -> Any:
    settings = request.app.state.settings
    with db.connection(settings) as conn:
        overview = service.users_overview(conn)
    overview = _USER_SORTS.get(sort, _USER_SORTS["activity"])(overview)
    template = "_users_table.html" if _is_htmx(request) else "users.html"
    return templates.TemplateResponse(
        request, template, {"users": overview, "sort": sort}
    )


@router.get("/search")
def jump_search(request: Request, q: str = Query(default="")) -> Any:
    """Structural, cleartext-only jump-to (plan §4.2) -- not a read/decrypt
    event, so unlike most routes here this does not call `_audit_read`; see
    `service.structural_search`'s docstring for why."""
    settings = request.app.state.settings
    with db.connection(settings) as conn:
        results = service.structural_search(conn, q)
    return templates.TemplateResponse(
        request, "_jump_search_results.html", {"query": q, "results": results}
    )


_USER_NUMBERS_SORTS = {
    "number": lambda rows: sorted(rows, key=lambda n: n["e164"]),  # repo already orders by e164
    "messages": lambda rows: sorted(rows, key=lambda n: n["message_count"], reverse=True),
}


@router.get("/users/{user_id}")
def user_detail(request: Request, user_id: UUID, sort: str = "number") -> Any:
    settings = request.app.state.settings
    with db.connection(settings) as conn:
        detail = service.user_detail(conn, user_id)
    if detail is None:
        raise _not_found("user")
    numbers = _USER_NUMBERS_SORTS.get(sort, _USER_NUMBERS_SORTS["number"])(detail["numbers"])
    template = "_user_numbers_table.html" if _is_htmx(request) else "user_detail.html"
    return templates.TemplateResponse(
        request,
        template,
        {"user": detail["user"], "user_id": user_id, "numbers": numbers, "sort": sort},
    )


# --- numbers / reading view -----------------------------------------------

_CONVERSATION_SORTS = {
    # conversation_index already returns most-recent-first (plan §4.1).
    "recency": lambda rows: rows,
    "count": lambda rows: sorted(rows, key=lambda c: c.message_count, reverse=True),
}


@router.get("/numbers/{number_id}")
def number_reading_view(
    request: Request,
    number_id: UUID,
    sort: str = "recency",
    operator: Operator = Depends(get_operator),
) -> Any:
    ctx = get_app_context(request)
    settings = request.app.state.settings
    with db.connection(settings) as conn:
        number = numbers_repo.get_by_id(conn, number_id)
        if number is None:
            raise _not_found("number")
        owner = users_repo.get_by_id(conn, number["user_id"])
        index = service.conversation_index(conn, ctx.field_aead, number_id)
        _audit_read(conn, operator, index.scope)
    conversations = _CONVERSATION_SORTS.get(sort, _CONVERSATION_SORTS["recency"])(
        index.conversations
    )
    template = "_conversation_list.html" if _is_htmx(request) else "number.html"
    return templates.TemplateResponse(
        request,
        template,
        {
            "number": number,
            "owner": owner,
            "conversations": conversations,
            "sort": sort,
        },
    )


@router.get("/numbers/{number_id}/thread")
def number_thread(
    request: Request,
    number_id: UUID,
    counterparty: str,
    offset: int = 0,
    limit: int = service.DEFAULT_THREAD_LIMIT,
    operator: Operator = Depends(get_operator),
) -> Any:
    ctx = get_app_context(request)
    settings = request.app.state.settings
    with db.connection(settings) as conn:
        window = service.thread_window(
            conn, ctx.field_aead, number_id, counterparty, offset=offset, limit=limit
        )
        _audit_read(conn, operator, window.scope)
    # offset==0 is the initial "click a conversation" load: render the h2 +
    # wrapper. offset>0 is a "load more" continuation, whose target is the
    # load-more button itself (hx-target="this", see _thread_messages.html)
    # -- returning the wrapper again would nest a second #thread-messages
    # div inside the first instead of appending the new page after it.
    template = "_thread.html" if offset == 0 else "_thread_messages.html"
    return templates.TemplateResponse(
        request,
        template,
        {"number_id": number_id, "window": window},
    )


@router.get("/numbers/{number_id}/search")
def number_search(
    request: Request,
    number_id: UUID,
    q: str = Query(default=""),
    operator: Operator = Depends(get_operator),
) -> Any:
    ctx = get_app_context(request)
    settings = request.app.state.settings
    with db.connection(settings) as conn:
        results = service.search(
            conn,
            ctx.field_aead,
            query=q,
            number_id=number_id,
            scope_label=f"within: number {number_id}",
        )
        if q.strip():
            # search() short-circuits on an empty query before scanning or
            # decrypting anything -- an empty search is a no-op, not a read,
            # and must not appear in the read-audit log as one.
            _audit_read(conn, operator, results.scope, search_applied=True)
    return templates.TemplateResponse(
        request,
        "_search_results.html",
        {"number_id": number_id, "results": results},
    )


# --- devices (technical view) ---------------------------------------------

_DEVICE_SORTS = {
    "label": lambda rows: rows,  # queries.list_devices already orders by label
    "messages": lambda rows: sorted(rows, key=lambda r: r["message_count"], reverse=True),
    "last_seen": lambda rows: sorted(
        rows,
        key=lambda r: r["device"]["last_seen_at"] or service.NEVER_ACTIVE,
        reverse=True,
    ),
}


@router.get("/devices")
def devices_list(request: Request, sort: str = "label") -> Any:
    settings = request.app.state.settings
    with db.connection(settings) as conn:
        overview = service.devices_overview(conn)
    overview = _DEVICE_SORTS.get(sort, _DEVICE_SORTS["label"])(overview)
    template = "_devices_table.html" if _is_htmx(request) else "devices.html"
    return templates.TemplateResponse(
        request, template, {"devices": overview, "sort": sort}
    )


@router.get("/devices/{device_id}")
def device_detail(request: Request, device_id: UUID) -> Any:
    settings = request.app.state.settings
    with db.connection(settings) as conn:
        detail = service.device_detail(conn, device_id)
    if detail is None:
        raise _not_found("device")
    return templates.TemplateResponse(
        request,
        "device_detail.html",
        {
            "device": detail["device"],
            "assignments": detail["assignments"],
            "message_count": detail["message_count"],
            "unassigned_count": detail["unassigned_count"],
        },
    )


# --- unassigned bucket ------------------------------------------------------


@router.get("/unassigned")
def unassigned_bucket(
    request: Request,
    device_id: UUID | None = None,
    after_ts: str | None = None,
    after_id: UUID | None = None,
    operator: Operator = Depends(get_operator),
) -> Any:
    ctx = get_app_context(request)
    settings = request.app.state.settings
    after = None
    if after_ts is not None and after_id is not None:
        from datetime import datetime

        after = (datetime.fromisoformat(after_ts), after_id)
    with db.connection(settings) as conn:
        page = service.unassigned_page(conn, ctx.field_aead, device_id=device_id, after=after)
        _audit_read(conn, operator, page.scope)
        devices = service.devices_overview(conn)
    return templates.TemplateResponse(
        request,
        "unassigned.html",
        {"page": page, "device_id": device_id, "devices": devices},
    )
