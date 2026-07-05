# Infrastructure

Cloud Run, DNS, and deployment notes for the SMS Ingest backend.

**Do not commit real project IDs, secrets, tokens, provider credentials, or the
production database URL.** Everything below uses placeholders; supply real values
at deploy time via your shell or a secret manager, never in this repo.

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

## Frugal-mode guardrails (locked for v1)

These are cost decisions locked in the private agent repo. Keep incremental
cloud spend near `$0/month` for the bootstrap workload:

- Cloud Run **request-based billing** (CPU allocated only during requests — the
  default; do **not** enable "CPU always allocated").
- **`--min-instances=0`** (no idle/minimum instances).
- Supabase **Free** tier; no Supabase paid custom domain.
- Minimal logging; **no paid log drains or paid observability**.
- **No** load balancer or paid edge feature unless explicitly approved.

## Build & deploy (Cloud Run)

Placeholders — replace `PROJECT_ID`, `REGION`, and the service/domain names.

```bash
# Build and push the image (Cloud Build; or `docker build` + push to Artifact Registry).
gcloud builds submit backend \
  --tag REGION-docker.pkg.dev/PROJECT_ID/sms-ingest/backend:latest

# Deploy. Request-based billing + no minimum instances = frugal defaults.
gcloud run deploy sms-ingest-backend \
  --image REGION-docker.pkg.dev/PROJECT_ID/sms-ingest/backend:latest \
  --region REGION \
  --platform managed \
  --min-instances 0 \
  --max-instances 2 \
  --concurrency 40 \
  --memory 512Mi \
  --cpu 1 \
  --no-allow-unauthenticated=false \
  --set-secrets \
      DATABASE_URL=sms-ingest-database-url:latest,\
TINK_PRIVATE_KEYSET_JSON=sms-ingest-tink-private:latest,\
TINK_PUBLIC_KEYSET_JSON=sms-ingest-tink-public:latest,\
SERVER_KEY_ID=sms-ingest-server-key-id:latest,\
FIELD_ENCRYPTION_KEY=sms-ingest-field-key:latest,\
TOKEN_HASH_PEPPER=sms-ingest-token-pepper:latest \
  --set-env-vars RETENTION_DAYS=90
```

Notes:
- The container listens on `$PORT` (Cloud Run injects it; the image defaults to
  `8080`). No port config needed beyond that.
- Generate keyset/pepper values with `sms-ingest-admin gen-keys` and store each
  in Secret Manager; never place them in this repo or in plain env vars.
- Apply migrations once against the production database
  (`sms-ingest-admin migrate` with `DATABASE_URL` set), or run the SQL in
  `backend/migrations/` via the Supabase SQL editor.
- Retention cleanup is a **manual CLI command** (`sms-ingest-admin run-retention`)
  for v1. Automating it via Cloud Scheduler or a Cloud Run job is an open item,
  deliberately deferred.

## Custom domain (GoDaddy DNS)

Map the configured API subdomain (a placeholder like `sms-api.example.com`; the
real value lives in the private agent repo's links notes, not here) to the
Cloud Run service:

```bash
gcloud run domain-mappings create \
  --service sms-ingest-backend \
  --domain sms-api.example.com \
  --region REGION
```

Then add the records Cloud Run returns to **GoDaddy DNS** for the domain
(typically a `CNAME` for a subdomain to `ghs.googlehosted.com`, or the `A`/`AAAA`
records Cloud Run prints). GoDaddy DNS is free with the existing domain — do not
add a Supabase or Cloud Run paid custom-domain add-on. Verify the mapping and TLS
certificate are active before issuing device provisioning QR codes that embed
this URL.

## Budget alerts (set up before real traffic)

Create a Cloud Billing budget with alert thresholds so any unexpected spend is
caught early on the near-`$0` target:

```bash
gcloud billing budgets create \
  --billing-account BILLING_ACCOUNT_ID \
  --display-name "sms-ingest v1" \
  --budget-amount 5USD \
  --threshold-rule percent=0.5 \
  --threshold-rule percent=0.9 \
  --threshold-rule percent=1.0
```

Scope the budget to the project once created, and route alert notifications to an
email/Pub/Sub channel you monitor.

## Pre-release checklist

- [ ] Confirm GoDaddy DNS + Cloud Run domain mapping resolve and serve TLS for
      the configured API base URL.
- [ ] All secrets in Secret Manager; none in the repo or plain env vars.
- [ ] Migrations applied to the production database.
- [ ] Budget alert active and scoped to the project.
- [ ] `--min-instances=0` and request-based billing confirmed on the service.
