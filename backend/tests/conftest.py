"""Shared test fixtures.

Unit tests (crypto, dedupe, token hashing) run anywhere. Integration tests
request the ``pg_conn`` fixture, which skips when Postgres is unreachable
(e.g. no local ``infra/docker-compose.yml`` DB). Point ``DATABASE_URL`` at a
disposable database before running the integration suite.
"""

from __future__ import annotations

import base64
import io
import json
import os

import psycopg
import pytest
import tink
from psycopg.rows import dict_row
from tink import aead, cleartext_keyset_handle, hybrid

from app import db
from app.config import Settings
from app.context import AppContext
from app.core import crypto
from app.models.api import EncryptionMeta, UploadBatchRequest

DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/sms_ingest"
DEFAULT_API_BASE_URL = "https://sms-api.example.com"


def _compact(handle: tink.KeysetHandle) -> str:
    stream = io.StringIO()
    cleartext_keyset_handle.write(tink.JsonKeysetWriter(stream), handle)
    return json.dumps(json.loads(stream.getvalue()), separators=(",", ":"))


@pytest.fixture(scope="session")
def keys() -> dict:
    hybrid.register()
    aead.register()
    priv = tink.new_keyset_handle(
        hybrid.hybrid_key_templates.DHKEM_X25519_HKDF_SHA256_HKDF_SHA256_AES_256_GCM
    )
    pub = priv.public_keyset_handle()
    field = tink.new_keyset_handle(aead.aead_key_templates.AES256_GCM)
    pub_json = _compact(pub)
    return {
        "priv_json": _compact(priv),
        "pub_json": pub_json,
        "field_json": _compact(field),
        "pin": crypto.compute_key_pin(pub_json),
        "key_id": "server-key-test",
        "pepper": "test-pepper",
        "encrypt": pub.primitive(hybrid.HybridEncrypt),
    }


@pytest.fixture
def settings(keys) -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL", DEFAULT_DB_URL),
        tink_private_keyset_json=keys["priv_json"],
        tink_public_keyset_json=keys["pub_json"],
        server_key_id=keys["key_id"],
        field_encryption_key=keys["field_json"],
        token_hash_pepper=keys["pepper"],
        api_base_url=DEFAULT_API_BASE_URL,
        retention_days=90,
    )


@pytest.fixture
def ctx(settings) -> AppContext:
    return AppContext.from_settings(settings)


@pytest.fixture
def encrypt_batch(keys):
    def _enc(plaintext: dict, context_info: dict) -> str:
        ct = keys["encrypt"].encrypt(
            json.dumps(plaintext).encode("utf-8"),
            crypto.canonical_context_info(context_info),
        )
        return base64.urlsafe_b64encode(ct).rstrip(b"=").decode("ascii")

    return _enc


@pytest.fixture
def make_message():
    def _m(
        *,
        dedupe_id="dedupe-1",
        sender="+15551230000",
        body="hello world",
        direction="inbox",
        sms_received_at="2026-07-01T12:00:00Z",
        client_message_id="msg-1",
        thread_hint=None,
        sim_info=None,
    ) -> dict:
        msg = {
            "client_message_id": client_message_id,
            "dedupe_id": dedupe_id,
            "direction": direction,
            "sender": sender,
            "body": body,
            "sms_received_at": sms_received_at,
        }
        if thread_hint is not None:
            msg["thread_hint"] = thread_hint
        if sim_info is not None:
            msg["sim_info"] = sim_info
        return msg

    return _m


@pytest.fixture
def make_request(keys, encrypt_batch):
    def _make(
        messages,
        *,
        client_batch_id="batch-1",
        api_base_url=DEFAULT_API_BASE_URL,
        scheme=None,
        server_key_id=None,
        server_key_pin=None,
        context_info=None,
        encrypt_context=None,
        ciphertext=None,
    ) -> UploadBatchRequest:
        ctx_info = context_info or {
            "api_base_url": api_base_url,
            "payload_type": "sms_batch",
            "version": 1,
            "client_batch_id": client_batch_id,
        }
        if ciphertext is None:
            plaintext = {
                "schema_version": 1,
                "device": {
                    "app_instance_id": "dev-1",
                    "android_sdk": 35,
                    "app_version": "1.0.0",
                },
                "messages": messages,
            }
            ciphertext = encrypt_batch(
                plaintext, encrypt_context if encrypt_context is not None else ctx_info
            )
        return UploadBatchRequest(
            version=1,
            device_time="2026-07-05T00:00:00Z",
            client_batch_id=client_batch_id,
            encryption=EncryptionMeta(
                scheme=scheme or crypto.SCHEME,
                server_key_id=server_key_id or keys["key_id"],
                server_key_pin=server_key_pin or keys["pin"],
            ),
            ciphertext=ciphertext,
            context_info=ctx_info,
        )

    return _make


@pytest.fixture
def pg_conn(settings):
    """A committed psycopg connection to a freshly-migrated, empty schema.

    Skips the test when the database is unreachable.
    """
    try:
        conn = psycopg.connect(
            settings.database_url,
            row_factory=dict_row,
            autocommit=True,
            connect_timeout=2,
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres not reachable at {settings.database_url}: {exc}")
    try:
        db.apply_migrations(conn)
        conn.execute(
            "truncate audit_events, sms_records, upload_batches, devices "
            "restart identity cascade"
        )
        yield conn
    finally:
        conn.close()


@pytest.fixture
def client(settings, ctx, pg_conn):
    """FastAPI TestClient bound to the test settings/context and DB.

    Depends on ``pg_conn`` so it inherits the skip-if-no-DB behavior and a clean
    schema. Resets the global connection pool around the test.
    """
    from fastapi.testclient import TestClient

    from app.main import create_app

    db.close_pool()
    app = create_app(settings)
    app.state.ctx = ctx
    with TestClient(app) as test_client:
        yield test_client
    db.close_pool()
