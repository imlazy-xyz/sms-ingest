# Backend

FastAPI service for encrypted SMS batch ingestion (v1). Receives Google Tink
HPKE-encrypted JSON batches from provisioned Android devices, decrypts them on
the ingestion path only, stores sensitive fields encrypted, dedupes retries, and
writes an audit trail. Deployed to Cloud Run against Supabase Postgres.

## Layout

```text
app/
  main.py            FastAPI app factory (app.main:app)
  config.py          Environment-backed settings (secrets optional at import)
  db.py              Connection pool helper
  api/               HTTP routing only (health, uploads)
  services/          Workflows (ingestion, provisioning)
  repositories/      Database reads/writes
  core/              auth, tokens, crypto (HPKE), field_crypto, dedupe, audit, retention
  models/            Request/response/domain types
cli/main.py          Admin CLI (sms-ingest-admin)
migrations/          SQL migrations (0001_initial.sql)
tests/               Unit tests (run without a database)
```

## API

- `GET /v1/health` — liveness/readiness check.
- `POST /v1/uploads/sms-batches` — authenticated, encrypted SMS batch ingest.

## Admin CLI

Installed as `sms-ingest-admin` (or `python -m cli.main`):

| Command | Purpose |
| --- | --- |
| `gen-keys` | Generate HPKE/field keysets + token pepper, print as env values. |
| `migrate` | Apply SQL migrations. |
| `create-device --label L` | Create a device; print one-time provisioning QR JSON. |
| `revoke-device --device-id ID` | Revoke a device token. |
| `rotate-token --device-id ID` | Rotate a device token; print new QR JSON. |
| `show-retention` | Show the active retention window. |
| `set-retention --days N` | Set the retention window. |
| `run-retention` | Delete expired SMS records (idempotent). |

## Local development

```bash
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'

# Local Postgres for integration work (dev/test only, never production):
docker compose -f ../infra/docker-compose.yml up -d
cp .env.example .env          # then fill in secrets via `sms-ingest-admin gen-keys`

pytest                        # unit suite runs without a database
uvicorn app.main:app --reload
```

Never commit `.env`, real keyset material, tokens, or a Supabase connection
string. Never log SMS plaintext, decrypted payloads, tokens, secrets, or key
material.

## Deployment

Cloud Run image is built from `backend/Dockerfile` (the single source of truth
for the deployed image). See `../infra/README.md` for the Cloud Run + GoDaddy
DNS deployment and budget-guardrail notes.

## Pinned versions

Resolved and verified during the scaffold, on **Python 3.11**. `pyproject.toml`
declares compatible ranges; these are the exact versions the suite was validated
against.

Runtime:

| Package | Version |
| --- | --- |
| fastapi | 0.139.0 |
| starlette (via fastapi) | 1.3.1 |
| uvicorn[standard] | 0.50.0 |
| pydantic | 2.13.4 |
| pydantic-settings | 2.14.2 |
| psycopg[binary] | 3.3.4 |
| psycopg-pool | 3.3.1 |
| tink | 1.15.0 |
| anyio (transitive) | 4.14.1 |

Dev:

| Package | Version |
| --- | --- |
| pytest | 9.1.1 |
| httpx | 0.28.1 |

Tink HPKE key type: `DHKEM_X25519_HKDF_SHA256_HKDF_SHA256_AES_256_GCM`
(decision locked in the private agent repo's `decisions.md`).
