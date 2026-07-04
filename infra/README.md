# Infrastructure

Cloud Run, DNS, and deployment notes will live here.

Do not commit real project IDs, secrets, tokens, or provider credentials.

## Local dev environment

`docker-compose.yml` runs a local Postgres for backend dev/integration tests. This is dev/test only and never touches the production Supabase instance.

```bash
docker compose -f infra/docker-compose.yml up -d
```

Copy `backend/.env.example` to `backend/.env` and point `DATABASE_URL` at `localhost` (or `db` if running inside the agent sandbox).
