"""Ownership curation + resolution workflow.

Populates ``sms_records.owner_number_id`` from operator-supplied SIM
assignments. No write-time stamping — this is the only place ownership gets
stamped (see the migration 0002 columns and the CLI verbs that call in here).

``sim_info_enc`` decrypts to a bare subId string (e.g. ``"1"``), not JSON —
that is exactly what the device sends as ``sim_info`` (see
``app.services.ingestion`` / the Android SMS capture path). Decrypt failures
or a missing/unparseable subId are treated as "unmapped" (leave/clear
``owner_number_id``), never raised — a resolution pass must not crash on one
bad row.

Never log or print decrypted SMS content, sender, or body. Printing the
decrypted subId itself (a bare digit like "1"/"2") is the sanctioned curation
aid for ``list-observed-sims`` — it is not SMS content — but it must never be
written to audit metadata or logs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg
from tink import aead

from app.core import audit, field_crypto
from app.repositories import numbers, sim_assignments, sms_records
from app.repositories import users as users_repo

_SIM_INFO_FIELD = "sim_info"


def create_user(conn: psycopg.Connection, *, display_name: str) -> dict[str, Any]:
    with conn.transaction():
        row = users_repo.insert(conn, display_name=display_name)
        audit.record(
            conn,
            audit.USER_CREATED,
            actor_type=audit.ACTOR_ADMIN,
            metadata={"user_id": str(row["id"])},
        )
    return row


def create_number(
    conn: psycopg.Connection,
    *,
    e164: str,
    user_id: UUID | str,
    label: str | None = None,
    iccid: str | None = None,
) -> dict[str, Any]:
    with conn.transaction():
        row = numbers.insert(conn, e164=e164, user_id=user_id, label=label, iccid=iccid)
        audit.record(
            conn,
            audit.NUMBER_CREATED,
            actor_type=audit.ACTOR_ADMIN,
            metadata={"number_id": str(row["id"])},
        )
    return row


def _decrypt_sub_id(field_aead: aead.Aead, sim_info_enc: bytes | None) -> int | None:
    """Best-effort decrypt + parse. Returns None (never raises) on any
    missing/undecryptable/non-integer value — those rows simply stay
    unassigned (§ ownership model: absent/unmapped subId -> NULL)."""
    if sim_info_enc is None:
        return None
    try:
        plaintext = field_crypto.decrypt_field(field_aead, _SIM_INFO_FIELD, sim_info_enc)
    except Exception:
        return None
    if plaintext is None:
        return None
    try:
        return int(plaintext)
    except (TypeError, ValueError):
        return None


@dataclass
class ResolveResult:
    scanned: int = 0
    stamped: int = 0
    cleared: int = 0
    unmapped: int = 0


def _resolve_rows(
    conn: psycopg.Connection,
    field_aead: aead.Aead,
    rows: list[dict[str, Any]],
    *,
    is_restamp: bool,
) -> ResolveResult:
    result = ResolveResult(scanned=len(rows))
    # Cache (device_id, sub_id) -> full assignment interval history within
    # this pass, to avoid a repeat lookup per row. Each row is matched against
    # the interval effective at *its own* sms_received_at, not just whichever
    # assignment happens to be open right now: a backlog row can be resolved
    # after a reassignment has already moved the currently-open interval to a
    # different number, and it must still land on the number that was current
    # when the message actually arrived (see test_resolve_uses_effective_
    # interval_not_current_after_reassignment).
    cache: dict[tuple[str, int], list[dict[str, Any]]] = {}

    for row in rows:
        sub_id = _decrypt_sub_id(field_aead, row.get("sim_info_enc"))
        if sub_id is None:
            result.unmapped += 1
            if is_restamp and row.get("owner_number_id") is not None:
                sms_records.clear_owner_number(conn, row["id"])
                result.cleared += 1
            continue

        key = (str(row["device_id"]), sub_id)
        if key not in cache:
            cache[key] = sim_assignments.list_for_device_sub(
                conn, device_id=row["device_id"], sub_id=sub_id
            )
        at = row["sms_received_at"]
        number_id = None
        current_number_id = None
        # Prefer the interval that strictly contains the message's own
        # timestamp (a backlog row synced late must still land on whichever
        # number was open when it was actually received, not on whatever is
        # open now). But a message can also predate assignment tracking
        # entirely — no interval's bounds cover it at all, most commonly a
        # brand-new assignment's own targeted resolve, where every prior
        # unstamped row predates the interval that was just opened for it.
        # For that case there's no better answer than "whichever assignment
        # is current", which is also exactly what a plain get_current() did
        # before this function existed, so it stays the fallback rather than
        # e.g. defaulting to the *earliest* known interval.
        for iv in cache[key]:
            if iv["effective_to"] is None:
                current_number_id = iv["number_id"]
            if iv["effective_from"] <= at and (
                iv["effective_to"] is None or at < iv["effective_to"]
            ):
                number_id = iv["number_id"]
                break
        if number_id is None:
            number_id = current_number_id

        if number_id is None:
            result.unmapped += 1
            if is_restamp and row.get("owner_number_id") is not None:
                sms_records.clear_owner_number(conn, row["id"])
                result.cleared += 1
            continue

        if is_restamp and row.get("owner_number_id") == number_id:
            # Already correctly stamped; nothing to do.
            continue

        sms_records.stamp_owner_number(conn, row["id"], number_id)
        result.stamped += 1

    return result


def resolve(
    conn: psycopg.Connection,
    field_aead: aead.Aead,
    *,
    device_id: UUID | str | None = None,
    page_size: int = 500,
) -> ResolveResult:
    """Default resolve: only rows with owner_number_id IS NULL. Cheap,
    steady-state path — does not re-decrypt already-stamped rows.

    Pages through the *entire* NULL candidate set via a keyset cursor rather
    than a single page, and must: unmapped rows stay owner_number_id IS NULL
    forever, so a single LIMIT page would starve out any mapped rows sitting
    behind a long unmapped prefix (e.g. every real-time-broadcast row, which
    has no subId at all — see SmsReceiver). Each page commits in its own
    transaction so a full backfill (~14,831 rows) isn't one giant txn."""
    total = ResolveResult()
    cursor: tuple[Any, UUID | str] | None = None
    while True:
        rows = sms_records.list_unassigned_for_resolution(
            conn, device_id=device_id, limit=page_size, after=cursor
        )
        if not rows:
            break
        with conn.transaction():
            page_result = _resolve_rows(conn, field_aead, rows, is_restamp=False)
        total.scanned += page_result.scanned
        total.stamped += page_result.stamped
        total.unmapped += page_result.unmapped
        last = rows[-1]
        cursor = (last["sms_received_at"], last["id"])
        if len(rows) < page_size:
            break

    with conn.transaction():
        audit.record(
            conn,
            audit.OWNERSHIP_RESOLVED,
            actor_type=audit.ACTOR_ADMIN,
            device_id=device_id,
            metadata={
                "mode": "default",
                "scanned": total.scanned,
                "stamped": total.stamped,
                "unmapped": total.unmapped,
            },
        )
    return total


def resolve_restamp(
    conn: psycopg.Connection,
    field_aead: aead.Aead,
    *,
    device_id: UUID | str | None = None,
    number_id: UUID | str | None = None,
    page_size: int = 500,
) -> ResolveResult:
    """Recompute over already-stamped rows too, for propagating a mislabel
    correction. Scope down with device_id and/or number_id when possible.
    Pages to exhaustion for the same reason as :func:`resolve`."""
    total = ResolveResult()
    cursor: tuple[Any, UUID | str] | None = None
    while True:
        rows = sms_records.list_for_restamp(
            conn,
            device_id=device_id,
            number_id=number_id,
            limit=page_size,
            after=cursor,
        )
        if not rows:
            break
        with conn.transaction():
            page_result = _resolve_rows(conn, field_aead, rows, is_restamp=True)
        total.scanned += page_result.scanned
        total.stamped += page_result.stamped
        total.cleared += page_result.cleared
        total.unmapped += page_result.unmapped
        last = rows[-1]
        cursor = (last["sms_received_at"], last["id"])
        if len(rows) < page_size:
            break

    with conn.transaction():
        audit.record(
            conn,
            audit.OWNERSHIP_RESOLVED,
            actor_type=audit.ACTOR_ADMIN,
            device_id=device_id,
            metadata={
                "mode": "restamp",
                "scanned": total.scanned,
                "stamped": total.stamped,
                "cleared": total.cleared,
                "unmapped": total.unmapped,
            },
        )
    return total


def list_observed_sims(
    conn: psycopg.Connection,
    field_aead: aead.Aead,
    device_id: UUID | str,
    *,
    page_size: int = 5000,
) -> list[int]:
    """Enumerate the distinct observed subIds for a device (by decrypting
    sim_info), for the operator to label via assign-sim. Sorted ascending.
    Pages through all matching rows via an id cursor rather than a single
    capped page, so a device with more sim_info rows than one page doesn't
    silently miss subIds introduced later in the id order."""
    seen: set[int] = set()
    cursor: UUID | str | None = None
    while True:
        rows = sms_records.list_distinct_sim_info_by_device(
            conn, device_id, limit=page_size, after_id=cursor
        )
        if not rows:
            break
        for row in rows:
            sub_id = _decrypt_sub_id(field_aead, row.get("sim_info_enc"))
            if sub_id is not None:
                seen.add(sub_id)
        cursor = rows[-1]["id"]
        if len(rows) < page_size:
            break
    return sorted(seen)


def assign_sim(
    conn: psycopg.Connection,
    field_aead: aead.Aead,
    *,
    device_id: UUID | str,
    sub_id: int,
    number_id: UUID | str,
    correction: bool = False,
) -> dict[str, Any]:
    """Curate a (device, subId) -> number mapping. Picks the operation by
    case (see module docstring / plan §4.5):

    - No open assignment exists for (device, subId) -> open a new one, then
      a targeted `resolve` (NULL rows only).
    - An open assignment already exists and ``correction=True`` -> mutate the
      open row in place (it was mislabeled; the interval was never real),
      then a targeted `resolve --restamp` scoped to this device so the
      already-stamped-wrong rows get fixed too.
    - An open assignment already exists and ``correction=False`` -> a
      legitimate reassignment: close the old interval + open a new one; no
      restamp (past SMS genuinely belonged to the old number).

    Raises ValueError if an open assignment exists but ``correction`` wasn't
    explicitly requested one way or the other by the caller's intent — this
    function requires the caller (CLI) to have already decided, via
    ``correction``; it does not infer it.
    """
    existing = sim_assignments.get_current(conn, device_id=device_id, sub_id=sub_id)

    if existing is None:
        with conn.transaction():
            row = sim_assignments.open_new(
                conn, device_id=device_id, sub_id=sub_id, number_id=number_id
            )
            audit.record(
                conn,
                audit.SIM_ASSIGNED,
                actor_type=audit.ACTOR_ADMIN,
                device_id=device_id,
                metadata={"assignment_id": str(row["id"])},
            )
        resolve(conn, field_aead, device_id=device_id)
        return {"operation": "new_assignment", "assignment": row}

    if correction:
        with conn.transaction():
            sim_assignments.update_number_in_place(
                conn, assignment_id=existing["id"], number_id=number_id
            )
            audit.record(
                conn,
                audit.SIM_ASSIGNMENT_CORRECTED,
                actor_type=audit.ACTOR_ADMIN,
                device_id=device_id,
                metadata={"assignment_id": str(existing["id"])},
            )
        result = resolve_restamp(conn, field_aead, device_id=device_id)
        return {"operation": "correction", "assignment_id": existing["id"], "resolve": result}

    with conn.transaction():
        row = sim_assignments.reassign(
            conn, device_id=device_id, sub_id=sub_id, new_number_id=number_id
        )
        audit.record(
            conn,
            audit.SIM_REASSIGNED,
            actor_type=audit.ACTOR_ADMIN,
            device_id=device_id,
            metadata={"assignment_id": str(row["id"])},
        )
    # No restamp: past sms_records stamps stay attributed to the old number.
    resolve(conn, field_aead, device_id=device_id)
    return {"operation": "reassignment", "assignment": row}


def apply_curation_seed(
    conn: psycopg.Connection, field_aead: aead.Aead, entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Apply a batch of curation directives from a seed file (JSON list of
    ``{device_id, sub_id, number_id, correction?}`` objects), one
    ``assign_sim`` call per entry, in file order. Each entry picks its own
    operation by case exactly like a single ``assign-sim`` invocation — this
    is a batch convenience, not a different semantic path."""
    results: list[dict[str, Any]] = []
    for entry in entries:
        results.append(
            assign_sim(
                conn,
                field_aead,
                device_id=entry["device_id"],
                sub_id=int(entry["sub_id"]),
                number_id=entry["number_id"],
                correction=bool(entry.get("correction", False)),
            )
        )
    return results
