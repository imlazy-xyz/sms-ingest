"""Admin CLI for the SMS ingest backend (v1, no web admin UI).

Commands:
  gen-keys            Generate Tink keysets + pepper and print env-ready values.
  migrate             Apply SQL migrations to DATABASE_URL.
  create-device       Create a device and print its one-time QR provisioning JSON.
  revoke-device       Revoke a device token.
  rotate-token        Rotate a device's bearer token (keeps dedupe secret) and print QR.
  show-retention      Print the configured retention window (days).
  set-retention       Update the retention window (days).
  run-retention       Delete expired SMS records (idempotent) and audit the deletion.
  create-user         Create a user (display name only).
  create-number       Create a number (e164) owned by a user.
  reassign-number-owner  Change a number's current owner (--same-person or --different-owner).
  assign-sim          Curate a (device, subId) -> number mapping.
  apply-curation      Apply a batch of assign-sim directives from a JSON seed file.
  list-observed-sims  Enumerate distinct (device, subId) pairs seen for a device.
  resolve             Stamp owner_number_id on sms_records from current assignments.

Secrets (QR payloads, keysets, pepper) are printed to stdout for one-time use.
Do not log, commit, or store them. Ownership curation output (subIds,
resolve counts) is non-sensitive metadata, not SMS content — but never print
decrypted sender/body/thread_hint here.
"""

from __future__ import annotations

import argparse
import io
import json
import secrets
import sys
from datetime import date

import tink
from tink import aead, cleartext_keyset_handle, hybrid

from app import db
from app.config import get_settings
from app.core import crypto, field_crypto, retention
from app.repositories import app_config
from app.services import curation, provisioning


def _keyset_to_compact_json(handle: tink.KeysetHandle) -> str:
    stream = io.StringIO()
    cleartext_keyset_handle.write(tink.JsonKeysetWriter(stream), handle)
    return json.dumps(json.loads(stream.getvalue()), separators=(",", ":"))


def cmd_gen_keys(_args: argparse.Namespace) -> int:
    hybrid.register()
    aead.register()
    priv = tink.new_keyset_handle(
        hybrid.hybrid_key_templates.DHKEM_X25519_HKDF_SHA256_HKDF_SHA256_AES_256_GCM
    )
    pub = priv.public_keyset_handle()
    field = tink.new_keyset_handle(aead.aead_key_templates.AES256_GCM)

    priv_json = _keyset_to_compact_json(priv)
    pub_json = _keyset_to_compact_json(pub)
    field_json = _keyset_to_compact_json(field)
    pepper = secrets.token_urlsafe(32)
    server_key_id = f"server-key-{date.today():%Y-%m}"
    pin = crypto.compute_key_pin(pub_json)

    print("# Generated key material — store in Cloud Run secrets; never commit.", file=sys.stderr)
    print(f"# Server key pin (for QR/Android verification): {pin}", file=sys.stderr)
    print(f"SERVER_KEY_ID={server_key_id}")
    print(f"TINK_PRIVATE_KEYSET_JSON={priv_json}")
    print(f"TINK_PUBLIC_KEYSET_JSON={pub_json}")
    print(f"FIELD_ENCRYPTION_KEY={field_json}")
    print(f"TOKEN_HASH_PEPPER={pepper}")
    return 0


def cmd_migrate(_args: argparse.Namespace) -> int:
    settings = get_settings()
    with db.connection(settings) as conn:
        db.apply_migrations(conn)
    print("migrations applied", file=sys.stderr)
    return 0


def cmd_create_device(args: argparse.Namespace) -> int:
    settings = get_settings()
    with db.connection(settings) as conn:
        payload = provisioning.create_device(conn, settings, args.label)
    print("# One-time QR payload. Scan once; do not store or log.", file=sys.stderr)
    print(json.dumps(payload, indent=2))
    return 0


def cmd_revoke_device(args: argparse.Namespace) -> int:
    settings = get_settings()
    with db.connection(settings) as conn:
        changed = provisioning.revoke_device(conn, args.device_id)
    print("revoked" if changed else "no change (already revoked or unknown)", file=sys.stderr)
    return 0 if changed else 1


def cmd_rotate_token(args: argparse.Namespace) -> int:
    settings = get_settings()
    with db.connection(settings) as conn:
        payload = provisioning.rotate_token(conn, settings, args.device_id)
    if payload is None:
        print("unknown device", file=sys.stderr)
        return 1
    print("# New one-time QR payload after rotation. Scan once; do not store or log.", file=sys.stderr)
    print(json.dumps(payload, indent=2))
    return 0


def cmd_show_retention(_args: argparse.Namespace) -> int:
    settings = get_settings()
    with db.connection(settings) as conn:
        days = app_config.get_retention_days(conn, settings.retention_days)
    print(json.dumps({"retention_days": days}))
    return 0


def cmd_set_retention(args: argparse.Namespace) -> int:
    settings = get_settings()
    with db.connection(settings) as conn:
        app_config.set_retention_days(conn, args.days)
    print(json.dumps({"retention_days": args.days}), file=sys.stderr)
    return 0


def cmd_run_retention(_args: argparse.Namespace) -> int:
    settings = get_settings()
    with db.connection(settings) as conn:
        deleted = retention.run_cleanup(conn)
    print(json.dumps({"deleted_count": deleted}))
    return 0


def _field_aead(settings) -> aead.Aead:
    return field_crypto.load_field_aead(settings.require("field_encryption_key"))


def cmd_create_user(args: argparse.Namespace) -> int:
    settings = get_settings()
    with db.connection(settings) as conn:
        row = curation.create_user(conn, display_name=args.display_name)
    print(json.dumps({"id": str(row["id"]), "display_name": row["display_name"]}))
    return 0


def cmd_create_number(args: argparse.Namespace) -> int:
    settings = get_settings()
    with db.connection(settings) as conn:
        row = curation.create_number(
            conn,
            e164=args.e164,
            user_id=args.user_id,
            label=args.label,
            iccid=args.iccid,
        )
    print(
        json.dumps(
            {
                "id": str(row["id"]),
                "e164": row["e164"],
                "user_id": str(row["user_id"]),
                "label": row["label"],
            }
        )
    )
    return 0


def cmd_reassign_number_owner(args: argparse.Namespace) -> int:
    if args.same_person == args.different_owner:
        # argparse mutually-exclusive-required guarantees exactly one is True;
        # this is a belt-and-suspenders check against future wiring mistakes.
        print("exactly one of --same-person or --different-owner is required", file=sys.stderr)
        return 1
    settings = get_settings()
    with db.connection(settings) as conn:
        try:
            result = curation.reassign_number_owner(
                conn,
                number_id=args.number_id,
                new_user_id=args.user_id,
                same_person=args.same_person,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print(json.dumps(result))
    return 0


def cmd_assign_sim(args: argparse.Namespace) -> int:
    settings = get_settings()
    with db.connection(settings) as conn:
        result = curation.assign_sim(
            conn,
            _field_aead(settings),
            device_id=args.device_id,
            sub_id=args.sub_id,
            number_id=args.number_id,
            correction=args.correction,
        )
    print(json.dumps({"operation": result["operation"]}))
    return 0


def cmd_apply_curation(args: argparse.Namespace) -> int:
    settings = get_settings()
    with open(args.file, encoding="utf-8") as f:
        entries = json.load(f)
    if not isinstance(entries, list):
        print("seed file must contain a JSON list", file=sys.stderr)
        return 1
    with db.connection(settings) as conn:
        results = curation.apply_curation_seed(conn, _field_aead(settings), entries)
    print(json.dumps({"applied": len(results)}))
    return 0


def cmd_list_observed_sims(args: argparse.Namespace) -> int:
    settings = get_settings()
    with db.connection(settings) as conn:
        sub_ids = curation.list_observed_sims(conn, _field_aead(settings), args.device_id)
    print(json.dumps({"device_id": args.device_id, "sub_ids": sub_ids}))
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    settings = get_settings()
    with db.connection(settings) as conn:
        if args.restamp:
            result = curation.resolve_restamp(
                conn,
                _field_aead(settings),
                device_id=args.device_id,
                number_id=args.number_id,
            )
        else:
            if args.number_id is not None:
                print("--number is only valid with --restamp", file=sys.stderr)
                return 1
            result = curation.resolve(conn, _field_aead(settings), device_id=args.device_id)
    print(
        json.dumps(
            {
                "scanned": result.scanned,
                "stamped": result.stamped,
                "cleared": result.cleared,
                "unmapped": result.unmapped,
            }
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sms-ingest-admin", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("gen-keys", help="Generate keysets + pepper (prints env values).").set_defaults(func=cmd_gen_keys)
    sub.add_parser("migrate", help="Apply SQL migrations.").set_defaults(func=cmd_migrate)

    p = sub.add_parser("create-device", help="Create a device; print one-time QR JSON.")
    p.add_argument("--label", required=True)
    p.set_defaults(func=cmd_create_device)

    p = sub.add_parser("revoke-device", help="Revoke a device token.")
    p.add_argument("--device-id", required=True)
    p.set_defaults(func=cmd_revoke_device)

    p = sub.add_parser("rotate-token", help="Rotate a device token; print one-time QR JSON.")
    p.add_argument("--device-id", required=True)
    p.set_defaults(func=cmd_rotate_token)

    sub.add_parser("show-retention", help="Show retention window.").set_defaults(func=cmd_show_retention)

    p = sub.add_parser("set-retention", help="Set retention window (days).")
    p.add_argument("--days", required=True, type=int)
    p.set_defaults(func=cmd_set_retention)

    sub.add_parser("run-retention", help="Delete expired SMS records.").set_defaults(func=cmd_run_retention)

    p = sub.add_parser("create-user", help="Create a user.")
    p.add_argument("--display-name", required=True)
    p.set_defaults(func=cmd_create_user)

    p = sub.add_parser("create-number", help="Create a number owned by a user.")
    p.add_argument("--e164", required=True)
    p.add_argument("--user-id", required=True)
    p.add_argument("--label")
    p.add_argument("--iccid")
    p.set_defaults(func=cmd_create_number)

    p = sub.add_parser(
        "reassign-number-owner",
        help="Change a number's current owner. Ownership is derived dynamically "
        "(current-ownership, not frozen attribution), so this affects the whole "
        "message history, past and future, immediately.",
    )
    p.add_argument("--number-id", required=True)
    p.add_argument("--user-id", required=True, help="The new owner.")
    guard = p.add_mutually_exclusive_group(required=True)
    guard.add_argument(
        "--same-person",
        action="store_true",
        help="Old and new owner are the same real person (e.g. a duplicate-user "
        "cleanup or mislabel fix) -- current-ownership is correct as-is.",
    )
    guard.add_argument(
        "--different-owner",
        action="store_true",
        help="Old and new owner are genuinely different people. This still hands "
        "the number's entire past message history to the new owner -- there is "
        "no per-message freeze in v1 -- but records the distinction in the audit "
        "trail instead of reassigning silently under the same path as a "
        "same-person correction. Confirm this is really what you want.",
    )
    p.set_defaults(func=cmd_reassign_number_owner)

    p = sub.add_parser(
        "assign-sim",
        help="Curate a (device, subId) -> number mapping. Picks new/correction/"
        "reassignment by case; use --correction to mark a mislabel fix.",
    )
    p.add_argument("--device-id", required=True)
    p.add_argument("--sub-id", required=True, type=int)
    p.add_argument("--number-id", required=True)
    p.add_argument(
        "--correction",
        action="store_true",
        help="An open assignment already exists and was mislabeled; mutate it "
        "in place and restamp, instead of treating this as a reassignment.",
    )
    p.set_defaults(func=cmd_assign_sim)

    p = sub.add_parser(
        "apply-curation", help="Apply assign-sim directives from a JSON seed file."
    )
    p.add_argument("--file", required=True, help="Path to a JSON list of directives.")
    p.set_defaults(func=cmd_apply_curation)

    p = sub.add_parser(
        "list-observed-sims", help="Enumerate distinct (device, subId) pairs for a device."
    )
    p.add_argument("--device-id", required=True)
    p.set_defaults(func=cmd_list_observed_sims)

    p = sub.add_parser(
        "resolve",
        help="Stamp owner_number_id on sms_records. Default: only NULL rows. "
        "--restamp: recompute already-stamped rows too (mislabel correction).",
    )
    p.add_argument("--device-id", help="Scope to a device.")
    p.add_argument("--restamp", action="store_true", help="Recompute already-stamped rows.")
    p.add_argument("--number", dest="number_id", help="Scope --restamp to a current owner number.")
    p.set_defaults(func=cmd_resolve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
