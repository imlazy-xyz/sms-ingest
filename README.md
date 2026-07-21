# sms-ingest

Backend-first SMS ingestion project.

## Current Scope

- Python FastAPI backend: complete, deployed to Cloud Run, Supabase Postgres.
- Android app: Phase 1 (project scaffold) in progress, see `android/README.md`.

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
