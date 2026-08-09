"""Reader workflows: fetch encrypted rows, decrypt server-side, shape for views.

Decryption happens here and nowhere else in the reader. Keys live in the server
process; the browser only ever receives rendered HTML. Nothing in this module
logs, prints, or returns plaintext to anywhere but its own return values (which
the templates render).

Two deliberately different decrypt scopes — they are not interchangeable:

* **Conversation index** (:func:`conversation_index`) decrypts ``sender_enc``
  across *all* of a number's rows so the thread list is complete, and then
  decrypts exactly one ``body_enc`` per distinct counterparty for its preview.
  Cost is O(messages) sender decrypts + O(threads) body decrypts — the body cost
  does not grow with message volume.
* **Thread view** (:func:`thread_window`) is a fluid window: it decrypts senders
  to find the selected counterparty's messages, but decrypts ``body_enc`` only
  for the slice actually being rendered, expanding as the operator asks for more.

Reads are inbox-only: a one-sided received log, never a two-way conversation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from tink import aead

from app.core import field_crypto
from app.repositories import numbers as numbers_repo
from app.repositories import sms_records
from app.repositories import users as users_repo
from reader import queries

SENDER_FIELD = "sender"
BODY_FIELD = "body"
SIM_INFO_FIELD = "sim_info"

#: Shown in place of a value whose ciphertext will not decrypt (wrong/rotated
#: key, corrupt row). Surfaced honestly rather than hiding the row.
UNDECRYPTABLE = "(undecryptable)"

PREVIEW_CHARS = 80
DEFAULT_THREAD_LIMIT = 50
DEFAULT_SCAN_PAGE = 500


# --- decrypt helpers -------------------------------------------------------


def _decrypt(field_aead: aead.Aead, name: str, ciphertext: bytes | None) -> str | None:
    """Best-effort field decrypt. Returns ``None`` for a NULL column and
    :data:`UNDECRYPTABLE` when the ciphertext will not open — never raises, so
    one bad row cannot take down a whole view, and never includes the
    underlying error (which could echo material we do not want surfaced)."""
    if ciphertext is None:
        return None
    try:
        return field_crypto.decrypt_field(field_aead, name, ciphertext)
    except Exception:
        return UNDECRYPTABLE


def _preview(body: str | None, limit: int = PREVIEW_CHARS) -> str:
    if not body:
        return ""
    flat = " ".join(body.split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "…"


# --- read scope (audit seam) ----------------------------------------------


@dataclass
class ReadScope:
    """Sanitized description of what a read touched — the seam the audit
    middleware consumes. Counts and identifiers only; never content, never a
    decrypted sender or body."""

    view: str
    number_id: str | None = None
    user_id: str | None = None
    device_id: str | None = None
    rows_scanned: int = 0
    senders_decrypted: int = 0
    bodies_decrypted: int = 0

    def as_metadata(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "view": self.view,
            "rows_scanned": self.rows_scanned,
            "senders_decrypted": self.senders_decrypted,
            "bodies_decrypted": self.bodies_decrypted,
        }
        for key in ("number_id", "user_id", "device_id"):
            value = getattr(self, key)
            if value is not None:
                data[key] = str(value)
        return data


# --- view models -----------------------------------------------------------


@dataclass(frozen=True)
class Conversation:
    counterparty: str
    message_count: int
    last_received_at: datetime
    preview: str


@dataclass(frozen=True)
class Message:
    id: UUID
    received_at: datetime
    device_id: UUID
    sender: str
    body: str


@dataclass(frozen=True)
class UnassignedMessage:
    id: UUID
    received_at: datetime
    device_id: UUID
    sender: str
    preview: str
    sub_id: str | None


@dataclass
class ConversationIndex:
    conversations: list[Conversation] = field(default_factory=list)
    scope: ReadScope = field(default_factory=lambda: ReadScope(view="conversations"))


@dataclass
class ThreadWindow:
    counterparty: str = ""
    messages: list[Message] = field(default_factory=list)
    offset: int = 0
    has_more: bool = False
    scope: ReadScope = field(default_factory=lambda: ReadScope(view="thread"))

    @property
    def next_offset(self) -> int:
        return self.offset + len(self.messages)


@dataclass
class SearchResults:
    query: str = ""
    scope_label: str = ""
    messages: list[Message] = field(default_factory=list)
    truncated: bool = False
    scope: ReadScope = field(default_factory=lambda: ReadScope(view="search"))


@dataclass
class UnassignedPage:
    messages: list[UnassignedMessage] = field(default_factory=list)
    next_cursor: tuple[datetime, UUID] | None = None
    total: int = 0
    scope: ReadScope = field(default_factory=lambda: ReadScope(view="unassigned"))


# --- paging ----------------------------------------------------------------


def _iter_offset_pages(
    fetch: Callable[[int, int], list[dict[str, Any]]],
    *,
    page_size: int = DEFAULT_SCAN_PAGE,
    stop_after: int | None = None,
):
    """Yield rows from an ``limit``/``offset``-paginated repository method until
    it is exhausted, de-duplicating on row ``id``.

    The repository orders by ``sms_received_at desc`` with no tiebreaker, so
    rows sharing a timestamp can shift position between two offset queries and
    be seen twice (or missed within a page's own ordering). De-duplicating on
    ``id`` makes the traversal safe against the duplicate half of that, which is
    the half that would corrupt per-counterparty counts.
    """
    seen: set[Any] = set()
    offset = 0
    while True:
        rows = fetch(page_size, offset)
        if not rows:
            return
        for row in rows:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            yield row
            if stop_after is not None and len(seen) >= stop_after:
                return
        if len(rows) < page_size:
            return
        offset += page_size


# --- conversation index ----------------------------------------------------


def conversation_index(
    conn: psycopg.Connection,
    field_aead: aead.Aead,
    number_id: UUID | str,
    *,
    page_size: int = DEFAULT_SCAN_PAGE,
) -> ConversationIndex:
    """Complete thread list for a number.

    Decrypts ``sender_enc`` for every one of the number's rows (the grouping key
    is encrypted, so there is no DB-side ``group by``), then decrypts a single
    ``body_enc`` per distinct counterparty for the list preview.
    """
    scope = ReadScope(view="conversations", number_id=str(number_id))

    # counterparty -> [count, latest row]
    groups: dict[str, list[Any]] = {}
    for row in _iter_offset_pages(
        lambda limit, offset: sms_records.list_by_owner_number(
            conn, number_id, limit=limit, offset=offset
        ),
        page_size=page_size,
    ):
        scope.rows_scanned += 1
        sender = _decrypt(field_aead, SENDER_FIELD, row["sender_enc"]) or "(unknown)"
        scope.senders_decrypted += 1
        entry = groups.get(sender)
        if entry is None:
            groups[sender] = [1, row]
            continue
        entry[0] += 1
        if row["sms_received_at"] > entry[1]["sms_received_at"]:
            entry[1] = row

    conversations = []
    for sender, (count, latest) in groups.items():
        body = _decrypt(field_aead, BODY_FIELD, latest["body_enc"])
        scope.bodies_decrypted += 1
        conversations.append(
            Conversation(
                counterparty=sender,
                message_count=count,
                last_received_at=latest["sms_received_at"],
                preview=_preview(body),
            )
        )
    conversations.sort(key=lambda c: c.last_received_at, reverse=True)
    return ConversationIndex(conversations=conversations, scope=scope)


# --- thread view (fluid window) --------------------------------------------


def thread_window(
    conn: psycopg.Connection,
    field_aead: aead.Aead,
    number_id: UUID | str,
    counterparty: str,
    *,
    offset: int = 0,
    limit: int = DEFAULT_THREAD_LIMIT,
    page_size: int = DEFAULT_SCAN_PAGE,
) -> ThreadWindow:
    """One counterparty's received messages, newest first, as a growing window.

    Scans the number's rows decrypting senders only (cheap) to locate the
    thread's rows, stopping as soon as enough have been found, and decrypts
    ``body_enc`` for the requested slice alone. Asking for a later ``offset``
    costs more sender decrypts but only the new slice's body decrypts.
    """
    scope = ReadScope(view="thread", number_id=str(number_id))
    needed = offset + limit

    matches: list[dict[str, Any]] = []
    has_more = False
    for row in _iter_offset_pages(
        lambda page_limit, page_offset: sms_records.list_by_owner_number(
            conn, number_id, limit=page_limit, offset=page_offset
        ),
        page_size=page_size,
    ):
        scope.rows_scanned += 1
        sender = _decrypt(field_aead, SENDER_FIELD, row["sender_enc"]) or "(unknown)"
        scope.senders_decrypted += 1
        if sender != counterparty:
            continue
        if len(matches) >= needed:
            # One match past the window is all we need to know there is more.
            has_more = True
            break
        matches.append(row)

    window = matches[offset:needed]
    messages = []
    for row in window:
        body = _decrypt(field_aead, BODY_FIELD, row["body_enc"]) or ""
        scope.bodies_decrypted += 1
        messages.append(
            Message(
                id=row["id"],
                received_at=row["sms_received_at"],
                device_id=row["device_id"],
                sender=counterparty,
                body=body,
            )
        )
    return ThreadWindow(
        counterparty=counterparty,
        messages=messages,
        offset=offset,
        has_more=has_more,
        scope=scope,
    )


# --- scoped search ---------------------------------------------------------


def search(
    conn: psycopg.Connection,
    field_aead: aead.Aead,
    *,
    query: str,
    number_id: UUID | str | None = None,
    user_id: UUID | str | None = None,
    device_id: UUID | str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    scope_label: str = "",
    max_scan: int = 2000,
    max_results: int = 200,
    page_size: int = DEFAULT_SCAN_PAGE,
) -> SearchResults:
    """Search *within an already-narrowed window*, never globally.

    The caller narrows structurally first (number / user / device / date — all
    indexed); this decrypts that window and filters it in-process, because
    sender and body are encrypted and cannot be filtered at the DB. ``max_scan``
    bounds the window so a broad scope degrades into "narrow it further", not
    into decrypting the whole corpus.
    """
    scope = ReadScope(
        view="search",
        number_id=str(number_id) if number_id else None,
        user_id=str(user_id) if user_id else None,
        device_id=str(device_id) if device_id else None,
    )
    results = SearchResults(query=query, scope_label=scope_label, scope=scope)
    if not query.strip():
        return results

    if number_id is not None:
        def fetch(limit: int, offset: int) -> list[dict[str, Any]]:
            return sms_records.list_by_owner_number(conn, number_id, limit=limit, offset=offset)
    elif user_id is not None:
        def fetch(limit: int, offset: int) -> list[dict[str, Any]]:
            return sms_records.list_by_owner_user(conn, user_id, limit=limit, offset=offset)
    elif device_id is not None:
        def fetch(limit: int, offset: int) -> list[dict[str, Any]]:
            return sms_records.list_by_device(
                conn, device_id, since=since, until=until, limit=limit, offset=offset
            )
    else:
        # Refuse an unscoped search rather than silently scanning everything.
        raise ValueError("search requires a number, user, or device scope")

    needle = query.casefold()
    for row in _iter_offset_pages(fetch, page_size=page_size, stop_after=max_scan):
        scope.rows_scanned += 1
        sender = _decrypt(field_aead, SENDER_FIELD, row["sender_enc"]) or ""
        scope.senders_decrypted += 1
        body = _decrypt(field_aead, BODY_FIELD, row["body_enc"]) or ""
        scope.bodies_decrypted += 1
        if needle in sender.casefold() or needle in body.casefold():
            results.messages.append(
                Message(
                    id=row["id"],
                    received_at=row["sms_received_at"],
                    device_id=row["device_id"],
                    sender=sender,
                    body=body,
                )
            )
            if len(results.messages) >= max_results:
                results.truncated = True
                break
    if scope.rows_scanned >= max_scan:
        results.truncated = True
    return results


# --- unassigned bucket -----------------------------------------------------


def unassigned_page(
    conn: psycopg.Connection,
    field_aead: aead.Aead,
    *,
    device_id: UUID | str | None = None,
    after: tuple[datetime, UUID | str] | None = None,
    limit: int = 100,
) -> UnassignedPage:
    """Rows with no owner stamped yet, surfaced under device + raw subId.

    These are a normal state (no subId captured, or the SIM is not curated yet),
    not an error. The raw subId is shown because it is exactly what the operator
    labels against; it is display-only and never written to logs or audit.

    Paginated with the repository's keyset cursor (unassigned rows stay
    unassigned, so an offset-based page would keep re-serving the same head).
    """
    scope = ReadScope(
        view="unassigned", device_id=str(device_id) if device_id else None
    )
    rows = sms_records.list_unassigned_for_resolution(
        conn, device_id=device_id, limit=limit, after=after
    )
    messages = []
    for row in rows:
        scope.rows_scanned += 1
        sender = _decrypt(field_aead, SENDER_FIELD, row["sender_enc"]) or "(unknown)"
        scope.senders_decrypted += 1
        body = _decrypt(field_aead, BODY_FIELD, row["body_enc"])
        scope.bodies_decrypted += 1
        sub_id = _decrypt(field_aead, SIM_INFO_FIELD, row["sim_info_enc"])
        messages.append(
            UnassignedMessage(
                id=row["id"],
                received_at=row["sms_received_at"],
                device_id=row["device_id"],
                sender=sender,
                preview=_preview(body),
                sub_id=sub_id,
            )
        )
    next_cursor = None
    if len(rows) == limit and rows:
        last = rows[-1]
        next_cursor = (last["sms_received_at"], last["id"])
    return UnassignedPage(
        messages=messages,
        next_cursor=next_cursor,
        total=queries.count_unassigned(conn, device_id=device_id),
        scope=scope,
    )


# --- index pages (no decryption) -------------------------------------------


def users_overview(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Users with their number and message counts. No decryption: everything
    shown here is operator-supplied cleartext."""
    overview = []
    for user in users_repo.list_all(conn):
        user_numbers = numbers_repo.list_for_user(conn, user["id"])
        overview.append(
            {
                "user": user,
                "numbers": user_numbers,
                "message_count": queries.count_by_owner_user(conn, user["id"]),
            }
        )
    return overview


def user_detail(conn: psycopg.Connection, user_id: UUID | str) -> dict[str, Any] | None:
    user = users_repo.get_by_id(conn, user_id)
    if user is None:
        return None
    user_numbers = []
    for number in numbers_repo.list_for_user(conn, user_id):
        user_numbers.append(
            {**number, "message_count": queries.count_by_owner_number(conn, number["id"])}
        )
    return {"user": user, "numbers": user_numbers}


def devices_overview(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Technical devices view: label, status, last seen, message count. The
    SIMs/subIds a device has been assigned come from the curated assignments,
    not from decrypting message rows."""
    from app.repositories import sim_assignments

    overview = []
    for device in queries.list_devices(conn):
        overview.append(
            {
                "device": device,
                "message_count": sms_records.count_for_device(conn, device["id"]),
                "assignments": sim_assignments.list_for_device(conn, device["id"]),
                "unassigned_count": queries.count_unassigned(conn, device_id=device["id"]),
            }
        )
    return overview


def device_detail(
    conn: psycopg.Connection, device_id: UUID | str
) -> dict[str, Any] | None:
    from app.repositories import sim_assignments

    device = queries.get_device(conn, device_id)
    if device is None:
        return None
    assignments = []
    for assignment in sim_assignments.list_for_device(conn, device_id):
        number = numbers_repo.get_by_id(conn, assignment["number_id"])
        assignments.append({**assignment, "number": number})
    return {
        "device": device,
        "assignments": assignments,
        "message_count": sms_records.count_for_device(conn, device_id),
        "unassigned_count": queries.count_unassigned(conn, device_id=device_id),
    }
