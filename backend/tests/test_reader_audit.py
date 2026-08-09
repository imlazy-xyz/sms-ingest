"""Read-audit hook tests (integration: require Postgres via pg_conn).

Hard constraint under test: a recorded read row must contain no
SMS content, senders, bodies, tokens, or key material — only who/when/scope/
counts. We seed known "sensitive" strings that must never leak into the
audit row, then assert both structural allowlisting and absence of those
strings from the serialized metadata.
"""

from __future__ import annotations

import pytest

from app.core import audit as core_audit
from reader.audit import record_read

pytestmark = pytest.mark.integration

# Strings that must never appear in an audit_events row. Stand in for SMS
# body/sender/token/key material a careless caller might be tempted to log.
_SENSITIVE_BODY = "hey the secret code is 4471, don't tell anyone"
_SENSITIVE_SENDER = "+15559998888"
_FAKE_TOKEN = "device-bearer-token-abc123"
_FAKE_KEY_MATERIAL = "-----BEGIN PRIVATE KEY-----fakekeydata"


def test_record_read_writes_exactly_one_sanitized_row(pg_conn):
    number_id = "11111111-1111-1111-1111-111111111111"

    record_read(
        pg_conn,
        actor_id="operator",
        scope={"number_id": number_id, "view": "thread"},
        message_count=3,
        reason="thread_view",
    )

    rows = pg_conn.execute(
        "select event_type, actor_type, actor_id, metadata from audit_events"
    ).fetchall()
    assert len(rows) == 1

    row = rows[0]
    assert row["event_type"] == core_audit.READ_PERFORMED
    assert row["actor_type"] == core_audit.ACTOR_ADMIN
    assert row["actor_id"] == "operator"

    metadata = row["metadata"]
    assert metadata["message_count"] == 3
    assert metadata["scope"] == {"number_id": number_id, "view": "thread"}
    assert metadata["reason"] == "thread_view"

    # No sensitive content anywhere in the serialized row.
    serialized = str(row)
    for sensitive in (_SENSITIVE_BODY, _SENSITIVE_SENDER, _FAKE_TOKEN, _FAKE_KEY_MATERIAL):
        assert sensitive not in serialized


def test_record_read_rejects_disallowed_scope_keys(pg_conn):
    with pytest.raises(ValueError):
        record_read(
            pg_conn,
            actor_id="operator",
            scope={"body": _SENSITIVE_BODY},
            message_count=1,
        )
    # Nothing should have been written.
    count = pg_conn.execute("select count(*) as c from audit_events").fetchone()["c"]
    assert count == 0


def test_record_read_rejects_non_primitive_scope_values(pg_conn):
    with pytest.raises(ValueError):
        record_read(
            pg_conn,
            actor_id="operator",
            scope={"number_id": {"nested": "object"}},
            message_count=1,
        )
    count = pg_conn.execute("select count(*) as c from audit_events").fetchone()["c"]
    assert count == 0


def test_record_read_rejects_search_term_smuggled_as_scope_value(pg_conn):
    """A search term is chosen to match content, so it must never be audited.

    ``search_applied`` is a bool flag; there is no key for the term itself,
    and over-long string values are rejected outright.
    """
    with pytest.raises(ValueError):
        record_read(
            pg_conn,
            actor_id="operator",
            scope={"search_term": "secret code"},
            message_count=1,
        )
    with pytest.raises(ValueError):
        record_read(
            pg_conn,
            actor_id="operator",
            scope={"view": _SENSITIVE_BODY * 3},
            message_count=1,
        )
    count = pg_conn.execute("select count(*) as c from audit_events").fetchone()["c"]
    assert count == 0


def test_record_read_accepts_search_applied_flag(pg_conn):
    record_read(
        pg_conn,
        actor_id="operator",
        scope={"view": "thread", "search_applied": True},
        message_count=2,
    )
    row = pg_conn.execute("select metadata from audit_events").fetchone()
    assert row["metadata"]["scope"]["search_applied"] is True


def test_record_read_rejects_token_shaped_actor_id(pg_conn):
    with pytest.raises(ValueError):
        record_read(
            pg_conn,
            actor_id=_FAKE_KEY_MATERIAL * 4,
            scope={"view": "thread"},
            message_count=1,
        )
    with pytest.raises(ValueError):
        record_read(pg_conn, actor_id="", scope={"view": "thread"}, message_count=1)
    count = pg_conn.execute("select count(*) as c from audit_events").fetchone()["c"]
    assert count == 0


def test_record_read_rejects_bad_message_count(pg_conn):
    for bad in (-1, "3", True):
        with pytest.raises(ValueError):
            record_read(pg_conn, actor_id="operator", scope={"view": "thread"}, message_count=bad)
    count = pg_conn.execute("select count(*) as c from audit_events").fetchone()["c"]
    assert count == 0


def test_record_read_allows_multiple_reads_as_separate_rows(pg_conn):
    record_read(pg_conn, actor_id="operator", scope={"view": "conversation_index"}, message_count=10)
    record_read(pg_conn, actor_id="operator", scope={"view": "thread"}, message_count=2)

    count = pg_conn.execute("select count(*) as c from audit_events").fetchone()["c"]
    assert count == 2
