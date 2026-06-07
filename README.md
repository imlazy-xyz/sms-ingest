# sms-ingest

Backend-first SMS ingestion project.

## Current Scope

- Python FastAPI backend scaffold first.
- Supabase Postgres.
- Cloud Run deployment target.
- Android app implementation later.

## Security Baseline

- No real secrets, tokens, QR payloads, or Supabase project identifiers in this repo.
- Device ingestion uses opaque per-device bearer tokens.
- Upload batches are encrypted with Google Tink HPKE.
- Sensitive SMS fields are stored encrypted.
- Retention cleanup is manual CLI for bootstrap v1.

## Structure

```text
backend/
android/
infra/
scripts/
.github/workflows/
```
