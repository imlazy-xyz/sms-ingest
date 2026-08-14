"""Unit tests for reader.routers._is_recent (v2 §5 recency-signal styling).

Pure function, no Postgres needed -- separate from test_reader_routes.py's
integration tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from reader.routers import _RECENT_WINDOW, _is_recent


def test_is_recent_none_is_false():
    assert _is_recent(None) is False


def test_is_recent_just_inside_window():
    value = datetime.now(timezone.utc) - (_RECENT_WINDOW - timedelta(minutes=1))
    assert _is_recent(value) is True


def test_is_recent_just_outside_window():
    value = datetime.now(timezone.utc) - (_RECENT_WINDOW + timedelta(minutes=1))
    assert _is_recent(value) is False


def test_is_recent_naive_datetime_treated_as_utc():
    naive = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None)
    assert _is_recent(naive) is True
