"""Admin CLI for the SMS ingest backend (v1, no web admin UI).

Commands:
  gen-keys        Generate Tink keysets + pepper and print env-ready values.
  migrate         Apply SQL migrations to DATABASE_URL.
  create-device   Create a device and print its one-time QR provisioning JSON.
  revoke-device   Revoke a device token.
  rotate-token    Rotate a device's bearer token (keeps dedupe secret) and print QR.
  show-retention  Print the configured retention window (days).
  set-retention   Update the retention window (days).
  run-retention   Delete expired SMS records (idempotent) and audit the deletion.

Secrets (QR payloads, keysets, pepper) are printed to stdout for one-time use.
Do not log, commit, or store them.
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
from app.core import crypto, retention
from app.repositories import app_config
from app.services import provisioning


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
