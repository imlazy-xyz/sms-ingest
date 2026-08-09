"""CLI verb tests for the ownership curation commands (integration: require
Postgres via pg_conn). Exercises `cli.main` end to end by monkeypatching
`get_settings` so the CLI's own DB connection targets the test database.
"""

from __future__ import annotations

import json

import pytest

from app.core import field_crypto, tokens
from app.models.domain import Device
from app.services import ingestion
from cli import main as cli_main


@pytest.fixture
def cli_settings(monkeypatch, settings, pg_conn):
    """Point the CLI's own get_settings() at the test settings/DB, and reset
    its connection pool around the test (mirrors the `client` fixture's
    close_pool pattern)."""
    from app import db

    monkeypatch.setattr(cli_main, "get_settings", lambda: settings)
    db.close_pool()
    yield settings
    db.close_pool()


def _device(conn, keys, *, label="phone", raw="tok"):
    from app.repositories import devices

    prefix = tokens.token_prefix(raw)
    inserted = devices.insert(
        conn, label=label, token_prefix=prefix, token_hash=tokens.hash_token(raw, keys["pepper"])
    )
    return Device(id=inserted["id"], label=label, status="active", token_prefix=prefix)


def _ingest_with_sim(pg_conn, ctx, device, make_request, make_message, *, dedupe_id, sim_info):
    ingestion.ingest_batch(
        pg_conn,
        ctx,
        device,
        make_request(
            [make_message(dedupe_id=dedupe_id, sim_info=sim_info)], client_batch_id=dedupe_id
        ),
    )


def test_create_user_and_number(cli_settings, pg_conn, capsys):
    rc = cli_main.main(["create-user", "--display-name", "Alice"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    user_id = out["id"]

    rc = cli_main.main(
        ["create-number", "--e164", "+15551234567", "--user-id", user_id, "--label", "work"]
    )
    assert rc == 0
    out2 = json.loads(capsys.readouterr().out)
    assert out2["e164"] == "+15551234567"

    row = pg_conn.execute("select count(*) n from numbers").fetchone()
    assert row["n"] == 1


def test_assign_sim_and_resolve_cli(
    cli_settings, pg_conn, ctx, keys, make_request, make_message, capsys
):
    device = _device(pg_conn, keys)
    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="cli1", sim_info="1"
    )

    rc = cli_main.main(["create-user", "--display-name", "Bob"])
    assert rc == 0
    user_id = json.loads(capsys.readouterr().out)["id"]

    rc = cli_main.main(
        ["create-number", "--e164", "+15559990000", "--user-id", user_id]
    )
    assert rc == 0
    number_id = json.loads(capsys.readouterr().out)["id"]

    rc = cli_main.main(
        [
            "assign-sim",
            "--device-id",
            str(device.id),
            "--sub-id",
            "1",
            "--number-id",
            number_id,
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["operation"] == "new_assignment"

    row = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='cli1'"
    ).fetchone()
    assert str(row["owner_number_id"]) == number_id


def test_resolve_cli_default_vs_restamp(
    cli_settings, pg_conn, ctx, keys, make_request, make_message, capsys
):
    device = _device(pg_conn, keys)
    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="rescli1", sim_info="1"
    )

    rc = cli_main.main(["create-user", "--display-name", "Carol"])
    user_id = json.loads(capsys.readouterr().out)["id"]
    rc = cli_main.main(["create-number", "--e164", "+15550001111", "--user-id", user_id])
    num_a = json.loads(capsys.readouterr().out)["id"]
    rc = cli_main.main(["create-number", "--e164", "+15550002222", "--user-id", user_id])
    num_b = json.loads(capsys.readouterr().out)["id"]

    rc = cli_main.main(
        ["assign-sim", "--device-id", str(device.id), "--sub-id", "1", "--number-id", num_a]
    )
    assert rc == 0
    capsys.readouterr()

    # Simulate a mislabel at the DB level, then check default resolve does
    # NOT touch the already-stamped row.
    pg_conn.execute(
        "update sim_assignments set number_id=%s where device_id=%s and sub_id=1",
        (num_b, str(device.id)),
    )
    rc = cli_main.main(["resolve", "--device-id", str(device.id)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["scanned"] == 0

    row = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='rescli1'"
    ).fetchone()
    assert str(row["owner_number_id"]) == num_a

    # --restamp recomputes and picks up the new mapping.
    rc = cli_main.main(["resolve", "--device-id", str(device.id), "--restamp"])
    assert rc == 0
    out2 = json.loads(capsys.readouterr().out)
    assert out2["stamped"] == 1

    row2 = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='rescli1'"
    ).fetchone()
    assert str(row2["owner_number_id"]) == num_b


def test_resolve_cli_rejects_number_without_restamp(cli_settings, pg_conn, capsys):
    rc = cli_main.main(["resolve", "--number", "00000000-0000-0000-0000-000000000000"])
    assert rc == 1


def test_list_observed_sims_cli(
    cli_settings, pg_conn, ctx, keys, make_request, make_message, capsys
):
    device = _device(pg_conn, keys)
    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="los1", sim_info="1"
    )
    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="los2", sim_info="2"
    )
    rc = cli_main.main(["list-observed-sims", "--device-id", str(device.id)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["sub_ids"] == [1, 2]


def test_apply_curation_cli(
    cli_settings, pg_conn, ctx, keys, make_request, make_message, capsys, tmp_path
):
    device = _device(pg_conn, keys)
    _ingest_with_sim(
        pg_conn, ctx, device, make_request, make_message, dedupe_id="seedcli1", sim_info="1"
    )

    rc = cli_main.main(["create-user", "--display-name", "Dan"])
    user_id = json.loads(capsys.readouterr().out)["id"]
    rc = cli_main.main(["create-number", "--e164", "+15557778888", "--user-id", user_id])
    number_id = json.loads(capsys.readouterr().out)["id"]

    seed_file = tmp_path / "seed.json"
    seed_file.write_text(
        json.dumps(
            [{"device_id": str(device.id), "sub_id": 1, "number_id": number_id}]
        )
    )
    rc = cli_main.main(["apply-curation", "--file", str(seed_file)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["applied"] == 1

    row = pg_conn.execute(
        "select owner_number_id from sms_records where dedupe_id='seedcli1'"
    ).fetchone()
    assert str(row["owner_number_id"]) == number_id
