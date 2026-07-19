# Infrastructure

Deployment notes for the SMS Ingest backend.

**Do not commit real project IDs, secrets, tokens, provider credentials, or the
production database URL.** Everything below uses placeholders; supply real values
at deploy time via your shell or a secret manager, never in this repo.

## What lives where

Cloud infrastructure — the GCP project, enabled APIs, the Cloud Run service
definition, Secret Manager secret *containers*, Artifact Registry, the runtime
service account's IAM, and the billing budget — is provisioned and managed by
**Terraform**, in a separate private infrastructure repo. It is not created with
manual `gcloud` steps anymore.

This repo (the app) covers only what Terraform intentionally does **not** own:

- Local dev/test environment (`docker-compose.yml`).
- Supabase data-plane prep (`supabase-setup.sh`).
- Secret **values** (Terraform manages the containers; the payloads are set
  out-of-band — see below).
- Building and deploying the container **image** (Terraform ignores the image
  reference on purpose, so releases don't fight state).

## Local dev environment

`docker-compose.yml` runs a local Postgres for backend dev/integration tests.
This is dev/test only and never touches the production Supabase instance.

```bash
docker compose -f infra/docker-compose.yml up -d
```

Copy `backend/.env.example` to `backend/.env` and point `DATABASE_URL` at
`localhost` (or `db` if running inside the agent sandbox).

## Production topology (v1)

- **Compute:** Cloud Run service, built from `backend/Dockerfile`.
- **Database:** Supabase Postgres (Free tier target).
- **DNS:** GoDaddy, mapping the configured API subdomain to Cloud Run.
- **Secrets:** Google Secret Manager, injected as Cloud Run env vars.

The backend image comes only from `backend/Dockerfile`; the local compose file
above never builds the deployed image.

## Supabase environment prep

Run once against a new Supabase project (idempotent, re-runnable) via the
Management API — no MCP and no DB password required:

```bash
export SUPABASE_ACCESS_TOKEN=...   # revocable Personal Access Token
export SUPABASE_PROJECT_REF=...    # scopes changes to one project
./infra/supabase-setup.sh
```

`supabase-setup.sh` closes the anon Data API (drops `public` from the exposed
schemas), applies `backend/migrations/*.sql`, and enables row-level security
plus a `RESTRICTIVE` deny-all policy on all public tables. The table-owner
`postgres` role bypasses RLS, so the backend (which connects via `DATABASE_URL`)
is unaffected; the deny-all only hard-blocks the anon/authenticated roles. The
policy is `RESTRICTIVE` on purpose — AND-combined, so no future permissive policy
can silently re-grant access. Do not "fix" these tables by adding permissive
policies (Supabase's `rls_enabled_no_policy` linter advisory is expected here and
is satisfied by the deny-all). Revoke the access token once prep is confirmed.

## Secret values

Terraform creates the six Secret Manager *containers*; their **values** are set
out-of-band and never enter Terraform state or this repo. Generate keyset/pepper
values with `sms-ingest-admin gen-keys` and add each as a new secret version:

```bash
gcloud secrets versions add SECRET_ID --data-file=-   # pipe the value in; never a file on disk
```

The Cloud Run service (Terraform-managed) reads these via `--set-secrets`-style
`value_source` env refs at `latest`.

## Build & deploy the image

Deploy an **immutable, digest-pinned** image — never `:latest`. Terraform owns
the rest of the service config (env, secrets, scaling, concurrency) and ignores
the image reference, so this changes only the running image:

```bash
REGION=...            # e.g. us-central1
PROJECT_ID=...
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/sms-ingest/backend"
SHA="$(git rev-parse --short HEAD)"

# Build and push a SHA-tagged image (reproducible; one tag per commit).
gcloud builds submit backend --tag "${IMAGE}:${SHA}"

# Resolve the immutable digest and deploy by digest (exact revision, exact rollback).
DIGEST="$(gcloud artifacts docker images describe "${IMAGE}:${SHA}" \
  --format='value(image_summary.digest)')"
gcloud run services update sms-ingest-backend \
  --region "${REGION}" \
  --image "${IMAGE}@${DIGEST}"
```

Notes:
- `gcloud run services update --image` updates **only** the image; it does not
  touch env/secrets/scaling, which Terraform manages. Do not re-pass those flags
  here.
- The container listens on `$PORT` (Cloud Run injects it; the image defaults to
  `8080`).
- Apply DB migrations once against the production database
  (`sms-ingest-admin migrate` with `DATABASE_URL` set), or run the SQL in
  `backend/migrations/` via the Supabase SQL editor.
- Retention cleanup is a **manual CLI command** (`sms-ingest-admin run-retention`)
  for v1.

## Custom domain (GoDaddy DNS)

When a domain is available, the Cloud Run domain mapping is added in Terraform
(`google_cloud_run_domain_mapping`); then add the records Cloud Run returns to
**GoDaddy DNS** (typically a `CNAME` for a subdomain to `ghs.googlehosted.com`).
GoDaddy DNS is free with the existing domain — do not add a Supabase or Cloud Run
paid custom-domain add-on. Verify the mapping and TLS certificate are active
before issuing device provisioning QR codes that embed this URL.

## Frugal-mode guardrails (locked for v1)

Kept near `$0/month` for the bootstrap workload; the Terraform config enforces
the service-level ones:

- Cloud Run **request-based billing** (CPU allocated only during requests — do
  **not** enable "CPU always allocated").
- **`min-instances=0`** (no idle/minimum instances).
- Supabase **Free** tier; no Supabase paid custom domain.
- Minimal logging; **no paid log drains or paid observability**.
- **No** load balancer or paid edge feature unless explicitly approved.
- A billing budget with alert thresholds guards against unexpected spend.
