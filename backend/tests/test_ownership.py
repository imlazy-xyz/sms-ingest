"""Ownership data model tests: repositories + curation service + CLI verbs
(integration: require Postgres via pg_conn).

Uses synthetic Tink-encrypted sim_info (via the ``keys``/``ctx`` fixtures),
never real device data.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core import field_crypto, tokens
from app.models.domain import Device
from app.repositories import numbers, sim_assignments, sms_records, users
from app.services import curation, ingestion


def _device(conn, keys, *, label="phone", raw="tok"):
    from app.repositories import devices

    prefix = tokens.token_prefix(raw)
    inserted = devices.insert(
        conn,
        label=label,
        token_prefix=prefix,
        token_hash=tokens.hash_token(raw, keys["pepper"]),
    )
    return Device(id=inserted["id"], label=label, status="active", token_prefix=prefix)


def _ingest_with_sim(pg_conn, ctx, device, make_request, make_message, *, dedupe_id, sim_info):
    ingestion.ingest_batch(
        pg_conn,
        ctx,
        device,
        make_request(
            [make_message(dedupe_id=dedupe_id, sim_info=sim_info)],
            client_batch_id=dedupe_id,
        ),
    )


# --- users / numbers repos ------------------------------------------------


def test_users_repo_crud(pg_conn):
    row = users.insert(pg_conn, display_name="Alice")
    assert row["display_name"] == "Alice"
    fetched = users.get_by_id(pg_conn, row["id"])
    assert fetched["id"] == row["id"]
    assert any(u["id"] == row["id"] for u in users.list_all(pg_conn))


def test_numbers_repo_crud(pg_conn):
    user = users.insert(pg_conn, display_name="Bob")
    row = numbers.insert(pg_conn, e164="+15551230000", user_id=user["id"], label="work")
    assert row["e164"] == "+15551230000"
    assert numbers.get_by_id(pg_conn, row["id"])["id"] == row["id"]
    assert numbers.get_by_e164(pg_conn, "+15551230000")["id"] == row["id"]
    assert [n["id"] for n in numbers.list_for_user(pg_conn, user["id"])] == [row["id"]]

    other_user = users.insert(pg_conn, display_name="Carol")
    changed = numbers.set_user(pg_conn, row["id"], other_user["id"])
    assert changed == 1
    assert numbers.get_by_id(pg_conn, row["id"])["user_id"] == other_user["id"]


def test_numbers_e164_unique(pg_conn):
    user = users.insert(pg_conn, display_name="Dave")
    numbers.insert(pg_conn, e164="+15550000001", user_id=user["id"])
    with pytest.raises(Exception):
        numbers.insert(pg_conn, e164="+15550000001", user_id=user["id"])


# --- sim_assignments repo --------------------------------------------------


def test_sim_assignments_open_close_reassign(pg_conn):
    user = users.insert(pg_conn, display_name="Eve")
    num_a = numbers.insert(pg_conn, e164="+15551110000", user_id=user["id"])
    num_b = numbers.insert(pg_conn, e164="+15552220000", user_id=user["id"])
    from app.repositories import devices

    device = devices.insert(
        pg_conn, label="d", token_prefix="pfx", token_hash="hash1"
    )

    assert sim_assignments.get_current(pg_conn, device_id=device["id"], sub_id=1) is None

    opened = sim_assignments.open_new(
        pg_conn, device_id=device["id"], sub_id=1, number_id=num_a["id"]
    )
    current = sim_assignments.get_current(pg_conn, device_id=device["id"], sub_id=1)
    assert current["id"] == opened["id"]
    assert current["effective_to"] is None

    # Partial unique index: cannot open a second concurrent assignment for
    # the same (device, sub_id) without closing the first.
    with pytest.raises(Exception):
        sim_assignments.open_new(
            pg_conn, device_id=device["id"], sub_id=1, number_id=num_b["id"]
        )


def test_sim_assignments_reassign_closes_old_opens_new(pg_conn):
    user = users.insert(pg_conn, display_name="Frank")
    num_a = numbers.insert(pg_conn, e164="+15553330000", user_id=user["id"])
    num_b = numbers.insert(pg_conn, e164="+15554440000", user_id=user["id"])
    from app.repositories import devices

    device = devices.insert(pg_conn, label="d2", token_prefix="pfx2", token_hash="hash2")

    first = sim_assignments.open_new(
        pg_conn, device_id=device["id"], sub_id=2, number_id=num_a["id"]
    )
    second = sim_assignments.reassign(
        pg_conn, device_id=device["id"], sub_id=2, new_number_id=num_b["id"]
    )

    closed = sim_assignments.get_by_id(pg_conn, first["id"])
    assert closed["effective_to"] is not None

    current = sim_assignments.get_current(pg_conn, device_id=device["id"], sub_id=2)
    assert current["id"] == second["id"]
    assert current["number_id"] == num_b["id"]


def test_sim_assignments_update_in_place(pg_conn):
    user = users.insert(pg_conn, display_name="Gina")
    num_a = numbers.insert(pg_conn, e164="+15555550000", user_id=user["id"])
    num_b = numbers.insert(pg_conn, e164="+15556660000", user_id=user["id"])
    from app.repositories import devices

    device = devices.insert(pg_conn, label="d3", token_prefix="pfx3", token_hash="hash3")
    opened = sim_assignments.open_new(
        pg_conn, device_id=device["id"], sub_id=3, number_id=num_a["id"]
    )
    changed = sim_assignments.update_number_in_place(
        pg_conn, assignment_id=opened["id"], number_id=num_b["id"]
    )
    assert changed == 1
    current = sim_assignments.get_current(pg_conn, device_id=device["id"], sub_id=3)
    assert current["id"] == opened["id"]  # same row, mutated
    assert current["number_id"] == num_b["id"]


# --- sms_records query methods ---------------------------------------------


def test_sms_records_query_methods(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    user = users.insert(pg_conn, display_name="Hank")
    number = numbers.insert(pg_conn, e164="+15557770000", user_id=user["id"])

    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="q1", sim_info="1"
    )
    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="q2", sim_info="1"
    )

    field_aead = field_crypto.load_field_aead(keys["field_json"])
    curation.assign_sim(
        pg_conn, field_aead, device_id=device.id, sub_id=1, number_id=number["id"]
    )

    by_number = sms_records.list_by_owner_number(pg_conn, number["id"])
    assert len(by_number) == 2

    by_user = sms_records.list_by_owner_user(pg_conn, user["id"])
    assert len(by_user) == 2

    by_device = sms_records.list_by_device(pg_conn, device.id)
    assert len(by_device) == 2

    unassigned = sms_records.list_unassigned_for_resolution(pg_conn)
    assert unassigned == []


# --- curation.resolve: default scope vs --restamp --------------------------


def test_resolve_default_only_touches_null_rows(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    user = users.insert(pg_conn, display_name="Ivy")
    num_a = numbers.insert(pg_conn, e164="+15558880000", user_id=user["id"])
    num_b = numbers.insert(pg_conn, e164="+15559990000", user_id=user["id"])
    field_aead = field_crypto.load_field_aead(keys["field_json"])

    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="r1", sim_info="5"
    )
    sim_assignments.open_new(pg_conn, device_id=device.id, sub_id=5, number_id=num_a["id"])
    result = curation.resolve(pg_conn, field_aead, device_id=device.id)
    assert result.stamped == 1

    row = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='r1'"
    ).fetchone()
    assert row["owner_number_id"] == num_a["id"]

    # Now mutate the assignment's target directly at the DB level (bypassing
    # curation) to simulate a stale mapping, and confirm plain `resolve`
    # does NOT touch the already-stamped row (default scope = NULL only).
    pg_conn.execute(
        "update sim_assignments set number_id=%s where device_id=%s and sub_id=5",
        (num_b["id"], device.id),
    )
    result2 = curation.resolve(pg_conn, field_aead, device_id=device.id)
    assert result2.scanned == 0
    row2 = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='r1'"
    ).fetchone()
    assert row2["owner_number_id"] == num_a["id"]  # unchanged


def test_resolve_restamp_recomputes_stamped_rows(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    user = users.insert(pg_conn, display_name="Jack")
    num_a = numbers.insert(pg_conn, e164="+15551000001", user_id=user["id"])
    num_b = numbers.insert(pg_conn, e164="+15551000002", user_id=user["id"])
    field_aead = field_crypto.load_field_aead(keys["field_json"])

    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="rs1", sim_info="6"
    )
    sim_assignments.open_new(pg_conn, device_id=device.id, sub_id=6, number_id=num_a["id"])
    curation.resolve(pg_conn, field_aead, device_id=device.id)

    # Mislabel: the assignment's target changes in place (simulating a
    # correction), and a restamp should re-propagate it.
    pg_conn.execute(
        "update sim_assignments set number_id=%s where device_id=%s and sub_id=6",
        (num_b["id"], device.id),
    )
    result = curation.resolve_restamp(pg_conn, field_aead, device_id=device.id)
    assert result.stamped == 1

    row = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='rs1'"
    ).fetchone()
    assert row["owner_number_id"] == num_b["id"]


def test_resolve_absent_sim_info_stays_unassigned(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    field_aead = field_crypto.load_field_aead(keys["field_json"])
    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="noinfo", sim_info=None
    )
    result = curation.resolve(pg_conn, field_aead, device_id=device.id)
    assert result.unmapped == 1
    assert result.stamped == 0
    row = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='noinfo'"
    ).fetchone()
    assert row["owner_number_id"] is None


def test_resolve_paginates_past_unmapped_prefix(pg_conn, ctx, keys, make_request, make_message):
    """A long run of unmapped (no-subId) rows must not starve out a mapped
    row that sorts later — resolve must page to exhaustion, not stop at one
    LIMIT page. Uses a page_size small enough to exercise pagination without
    ingesting hundreds of synthetic rows."""
    device = _device(pg_conn, keys)
    user = users.insert(pg_conn, display_name="Odell")
    number = numbers.insert(pg_conn, e164="+15550100001", user_id=user["id"])
    field_aead = field_crypto.load_field_aead(keys["field_json"])

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(5):
        _ingest_with_sim(
            pg_conn,
            ctx,
            device,
            make_request,
            make_message,
            dedupe_id=f"unmapped-prefix-{i}",
            sim_info=None,
        )
    # A later-timestamped, mapped row (would be past a small first page).
    ingestion.ingest_batch(
        pg_conn,
        ctx,
        device,
        make_request(
            [make_message(dedupe_id="mapped-tail", sim_info="42")],
            client_batch_id="mapped-tail",
        ),
    )
    sim_assignments.open_new(pg_conn, device_id=device.id, sub_id=42, number_id=number["id"])

    result = curation.resolve(pg_conn, field_aead, device_id=device.id, page_size=2)
    assert result.scanned == 6
    assert result.stamped == 1
    assert result.unmapped == 5

    row = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='mapped-tail'"
    ).fetchone()
    assert row["owner_number_id"] == number["id"]


def test_resolve_restamp_clears_now_unmapped_stamp(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    user = users.insert(pg_conn, display_name="Pia")
    number = numbers.insert(pg_conn, e164="+15550200002", user_id=user["id"])
    field_aead = field_crypto.load_field_aead(keys["field_json"])

    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="clr1", sim_info="21"
    )
    sim_assignments.open_new(pg_conn, device_id=device.id, sub_id=21, number_id=number["id"])
    curation.resolve(pg_conn, field_aead, device_id=device.id)
    row = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='clr1'"
    ).fetchone()
    assert row["owner_number_id"] == number["id"]

    # The assignment is closed with nothing reopened -> subId 21 is now
    # unmapped again. A restamp should clear the stale stamp back to NULL.
    sim_assignments.close_current(pg_conn, device_id=device.id, sub_id=21)
    result = curation.resolve_restamp(pg_conn, field_aead, device_id=device.id)
    assert result.cleared == 1

    row2 = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='clr1'"
    ).fetchone()
    assert row2["owner_number_id"] is None


def test_resolve_known_but_unmapped_stays_null(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    field_aead = field_crypto.load_field_aead(keys["field_json"])
    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="unmapped1", sim_info="99"
    )
    result = curation.resolve(pg_conn, field_aead, device_id=device.id)
    assert result.unmapped == 1
    row = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='unmapped1'"
    ).fetchone()
    assert row["owner_number_id"] is None


# --- assign_sim: the three cases -------------------------------------------


def test_assign_sim_new_assignment_resolves(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    user = users.insert(pg_conn, display_name="Karl")
    number = numbers.insert(pg_conn, e164="+15552000001", user_id=user["id"])
    field_aead = field_crypto.load_field_aead(keys["field_json"])

    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="a1", sim_info="7"
    )
    result = curation.assign_sim(
        pg_conn, field_aead, device_id=device.id, sub_id=7, number_id=number["id"]
    )
    assert result["operation"] == "new_assignment"
    row = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='a1'"
    ).fetchone()
    assert row["owner_number_id"] == number["id"]


def test_assign_sim_correction_mutates_and_restamps(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    user = users.insert(pg_conn, display_name="Liam")
    num_wrong = numbers.insert(pg_conn, e164="+15553000001", user_id=user["id"])
    num_right = numbers.insert(pg_conn, e164="+15553000002", user_id=user["id"])
    field_aead = field_crypto.load_field_aead(keys["field_json"])

    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="c1", sim_info="8"
    )
    curation.assign_sim(
        pg_conn, field_aead, device_id=device.id, sub_id=8, number_id=num_wrong["id"]
    )
    row = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='c1'"
    ).fetchone()
    assert row["owner_number_id"] == num_wrong["id"]

    # Same open assignment, now corrected -> mutate in place + restamp.
    result = curation.assign_sim(
        pg_conn,
        field_aead,
        device_id=device.id,
        sub_id=8,
        number_id=num_right["id"],
        correction=True,
    )
    assert result["operation"] == "correction"

    # Exactly one open assignment still exists for (device, subId) — mutated,
    # not a second row.
    all_assignments = sim_assignments.list_for_device(pg_conn, device.id)
    open_rows = [a for a in all_assignments if a["effective_to"] is None and a["sub_id"] == 8]
    assert len(open_rows) == 1
    assert open_rows[0]["number_id"] == num_right["id"]

    row2 = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='c1'"
    ).fetchone()
    assert row2["owner_number_id"] == num_right["id"]


def test_assign_sim_reassignment_closes_old_no_restamp(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    user = users.insert(pg_conn, display_name="Mia")
    num_old = numbers.insert(pg_conn, e164="+15554000001", user_id=user["id"])
    num_new = numbers.insert(pg_conn, e164="+15554000002", user_id=user["id"])
    field_aead = field_crypto.load_field_aead(keys["field_json"])

    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="re1", sim_info="9"
    )
    curation.assign_sim(
        pg_conn, field_aead, device_id=device.id, sub_id=9, number_id=num_old["id"]
    )
    row_before = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='re1'"
    ).fetchone()
    assert row_before["owner_number_id"] == num_old["id"]

    # SIM moves to a new number now — legitimate reassignment, not a
    # correction. Past SMS should stay attributed to the old number.
    result = curation.assign_sim(
        pg_conn, field_aead, device_id=device.id, sub_id=9, number_id=num_new["id"]
    )
    assert result["operation"] == "reassignment"

    row_after = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='re1'"
    ).fetchone()
    assert row_after["owner_number_id"] == num_old["id"]  # unchanged, no restamp

    # A closed interval for num_old and an open one for num_new now exist.
    current = sim_assignments.get_current(pg_conn, device_id=device.id, sub_id=9)
    assert current["number_id"] == num_new["id"]

    # A new message arriving after the reassignment resolves to the new number.
    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="re2", sim_info="9"
    )
    curation.resolve(pg_conn, field_aead, device_id=device.id)
    row_new = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='re2'"
    ).fetchone()
    assert row_new["owner_number_id"] == num_new["id"]


# --- list_observed_sims -----------------------------------------------------


def test_list_observed_sims_enumerates_distinct(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    field_aead = field_crypto.load_field_aead(keys["field_json"])
    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="s1", sim_info="1"
    )
    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="s2", sim_info="2"
    )
    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="s3", sim_info="1"
    )
    sub_ids = curation.list_observed_sims(pg_conn, field_aead, device.id)
    assert sub_ids == [1, 2]


# --- apply_curation_seed ----------------------------------------------------


def test_apply_curation_seed_batches_directives(pg_conn, ctx, keys, make_request, make_message):
    device = _device(pg_conn, keys)
    user = users.insert(pg_conn, display_name="Nora")
    num1 = numbers.insert(pg_conn, e164="+15555000001", user_id=user["id"])
    num2 = numbers.insert(pg_conn, e164="+15555000002", user_id=user["id"])
    field_aead = field_crypto.load_field_aead(keys["field_json"])

    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="seed1", sim_info="10"
    )
    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="seed2", sim_info="11"
    )

    entries = [
        {"device_id": str(device.id), "sub_id": 10, "number_id": str(num1["id"])},
        {"device_id": str(device.id), "sub_id": 11, "number_id": str(num2["id"])},
    ]
    results = curation.apply_curation_seed(pg_conn, field_aead, entries)
    assert len(results) == 2
    assert all(r["operation"] == "new_assignment" for r in results)

    row1 = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='seed1'"
    ).fetchone()
    row2 = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='seed2'"
    ).fetchone()
    assert row1["owner_number_id"] == num1["id"]
    assert row2["owner_number_id"] == num2["id"]
