"""Read-audit hook for the reader UI.

Every decrypt-read the reader performs must record **exactly one** sanitized
``audit_events`` row: who / when / scope / counts. Never SMS content,
senders, bodies, tokens, or key material.

Sanitization here is structural, not just disciplinary: :func:`record_read`
only accepts identifiers, a scope description, and counts — there is no
parameter through which a caller could pass a message body or sender by
accident. The reader's read/service layer should call this once per logical read
operation (e.g. once per "render this thread" or "render this conversation
list" request), after decryption, with the *shape* of what was read
(how many messages, which number/user/device scope) — never the decrypted
values themselves.

Usage from the reader's read path (service/router layer)::

    from reader.audit import record_read

    record_read(
        conn,
        actor_id="operator",           # who (v1: single operator; see reader.auth)
        scope={"number_id": str(number_id), "view": "thread"},
        message_count=len(decrypted_messages),
    )

This wraps :func:`app.core.audit.record` with the reader-specific event type
(``app.core.audit.READ_PERFORMED``) and the sanitized-by-construction
signature below. It does not open its own connection — callers pass the
connection they already hold (same pattern as ``app.core.audit.record``).
"""

from __future__ import annotations

from typing import Any

import psycopg

from app.core import audit as core_audit

#: Metadata keys allowed in a read-audit row. Enforced defensively in
#: :func:`record_read` even though the signature already restricts inputs —
#: belt-and-suspenders against a future caller passing an ad hoc dict.
_ALLOWED_SCOPE_KEYS = {
    "number_id",
    "user_id",
    "device_id",
    "view",
    "date_from",
    "date_to",
    # Whether a scoped search filter was applied — a bool, NOT the search
    # term. A search term is operator-entered text chosen to *match message
    # content*, so recording it would leak content by proxy.
    "search_applied",
}

#: Upper bound on ``actor_id`` / ``reason``. These are short machine labels;
#: the bound is a structural guard against a caller smuggling free text (or a
#: token) through a nominally-safe string field.
_MAX_LABEL_LEN = 64


def record_read(
    conn: psycopg.Connection,
    *,
    actor_id: str,
    scope: dict[str, Any],
    message_count: int,
    reason: str | None = None,
) -> None:
    """Record one sanitized read-audit event.

    Args:
        conn: an open connection (autocommit or inside the caller's
            transaction — same contract as ``app.core.audit.record``).
        actor_id: identifies the operator/session performing the read.
            Never a token or credential — an opaque id/label only.
        scope: structural narrowing info only (ids, view name, date
            range) — see :data:`_ALLOWED_SCOPE_KEYS`. No free-text.
        message_count: how many messages were decrypted/rendered in this
            read (a count, never the messages themselves).
        reason: optional short machine label (e.g. "thread_view",
            "conversation_index") — not free text describing content.

    Raises:
        ValueError: if ``scope`` contains a key outside the allowlist,
            or if any value can't be safely serialized (str/int/None/bool).
    """
    if not actor_id or len(actor_id) > _MAX_LABEL_LEN:
        raise ValueError(
            f"read-audit actor_id must be a non-empty label of at most "
            f"{_MAX_LABEL_LEN} chars. It identifies the operator — never pass "
            "a token, credential, or key."
        )
    if reason is not None and len(reason) > _MAX_LABEL_LEN:
        raise ValueError(
            f"read-audit reason must be a short machine label of at most "
            f"{_MAX_LABEL_LEN} chars, not free text describing content."
        )
    if not isinstance(message_count, int) or isinstance(message_count, bool) or message_count < 0:
        raise ValueError("read-audit message_count must be a non-negative int")

    unknown_keys = set(scope) - _ALLOWED_SCOPE_KEYS
    if unknown_keys:
        raise ValueError(
            f"read-audit scope contains disallowed keys {sorted(unknown_keys)}; "
            f"only {sorted(_ALLOWED_SCOPE_KEYS)} are permitted. Content, "
            "senders, bodies, tokens, and keys must never reach the audit log."
        )
    for key, value in scope.items():
        if value is not None and not isinstance(value, (str, int, bool)):
            raise ValueError(
                f"read-audit scope[{key!r}] must be str/int/bool/None, "
                f"got {type(value).__name__}"
            )
        if isinstance(value, str) and len(value) > _MAX_LABEL_LEN:
            raise ValueError(
                f"read-audit scope[{key!r}] exceeds {_MAX_LABEL_LEN} chars. "
                "Scope values are ids/labels/dates — never search terms that "
                "could echo message content."
            )

    metadata: dict[str, Any] = {"scope": scope, "message_count": message_count}
    if reason is not None:
        metadata["reason"] = reason

    core_audit.record(
        conn,
        core_audit.READ_PERFORMED,
        actor_type=core_audit.ACTOR_ADMIN,
        actor_id=actor_id,
        metadata=metadata,
    )
