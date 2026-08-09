# Admin Reader UI

Local-first, **read-only** web UI for browsing synced SMS attributed to users and
numbers. It is a separate ASGI app from the ingest service (`backend/app`), but
reuses the same shared code (`app.core`, `app.repositories`), the same database,
and the same key material.

**Local-only in v1.** It binds to loopback and is brought up on demand, not run
continuously. There is no cloud deployment for this app (see
[Cloud deployment](#cloud-deployment-not-in-v1)).

## Security posture

- **Loopback-only binding is the v1 access boundary.** There is no login in v1;
  the reader must never be published on a non-loopback interface.
- The rendered UI, shown to the local operator, is the **only** sanctioned place
  decrypted message content appears. Decryption happens server-side only.
- Never commit `.env`, real keyset material, tokens, or a real database URL.
  Never log SMS plaintext, decrypted payloads, tokens, or key material.

## Packaging layout

```text
backend/reader/
  Containerfile          Podman image for the reader app
  reader-pod.yaml        Declarative pod topology (reference; see note below)
  .env.example           Environment template -> copy to .env (gitignored)
  scripts/reader-up.sh   Bring the reader + local Postgres up on loopback
  scripts/reader-down.sh Tear it down cleanly
  main.py                ASGI entrypoint (`reader.main:app`) — see Entrypoint assumptions
```

Plus `backend/.containerignore`, which excludes `.env`/key material from the
image build context.

Container tooling here is **Podman**, not the Docker daemon.

`backend/.containerignore` keeps `.env` and key material out of the build
context — the reader image copies the whole `reader/` directory, so without it a
local `.env` would be baked into the image. If you ever build this image with
Docker instead of Podman, mirror those rules into a `.dockerignore`, because
Docker does not read `.containerignore`.

## Quick start

```bash
cd backend

# 1. Build the image. NOTE: build context is `backend/`, not `backend/reader/`,
#    because the reader imports the shared `app` package.
podman build -f reader/Containerfile -t sms-ingest-reader:local .

# 2. Configure secrets (never committed).
cp reader/.env.example reader/.env
#    Fill in values; generate key material with `sms-ingest-admin gen-keys`.

# 3. Up / down.
cd reader
./scripts/reader-up.sh            # http://127.0.0.1:8081
./scripts/reader-down.sh          # stop + remove pod, keep the DB volume
./scripts/reader-down.sh --purge  # also delete the local DB volume
```

Overridable via environment: `READER_PORT` (default `8081`), `DB_PORT`
(default `5433`, chosen so it does not collide with the ingest dev database in
`infra/docker-compose.yml`), `ENV_FILE` (default `.env`).

### If you cannot build the image locally

Some confined/nested container environments can run containers but cannot
*build* images. In that case build on a machine or CI runner with a working
container engine and transfer the image:

```bash
# On the build machine:
podman build -f reader/Containerfile -t sms-ingest-reader:local .
podman save -o reader.tar sms-ingest-reader:local

# On the target:
podman load -i reader.tar
```

## How loopback-only is enforced

Read this before changing any bind address:

- Inside the container, uvicorn binds **`0.0.0.0`**. That is correct and
  deliberate — the container has its own network namespace, and binding uvicorn
  to `127.0.0.1` there would make it unreachable through the port forward.
- The loopback guarantee comes from the **host publish mapping**:
  `podman pod create -p 127.0.0.1:8081:8081`. Both the reader port and the
  Postgres port are published on `127.0.0.1` only.
- Therefore `scripts/reader-up.sh` is the **source of truth** for the loopback
  binding. `reader-pod.yaml` expresses the same topology declaratively via
  `ports[].hostIP`, but honoring `hostIP` has varied across Podman versions, so
  the YAML is a reference/topology artifact — do not rely on it for the security
  property unless you have verified it on your Podman version.

## Pod topology

`scripts/reader-up.sh` creates one pod with two containers:

| Container | Image | Purpose |
| --- | --- | --- |
| `sms-ingest-reader-app` | `sms-ingest-reader:local` | The reader ASGI app |
| `sms-ingest-reader-db` | `postgres:16-alpine` | Local Postgres |

They share the pod's network namespace, so the reader reaches Postgres at
`127.0.0.1:5432` — the *in-pod* port, which stays `5432` regardless of which host
port `DB_PORT` publishes it on. The up script sets `DATABASE_URL` accordingly,
overriding whatever is in `.env`.

Postgres data lives in the named volume `sms-ingest-reader-db-data`, which
survives `reader-down.sh` unless you pass `--purge`.

## Entrypoint assumptions

The packaging in this directory was written before `reader/main.py` existed. It
assumes:

1. **The ASGI app object is importable as `reader.main:app`** — i.e. a module
   `backend/reader/main.py` exposing a module-level `app`. This is what the
   Containerfile's `CMD` runs via uvicorn.
2. **The app reads `DATABASE_URL` and key material from the environment**, using
   the existing `app.config` settings pattern. The up script injects them via
   `--env-file` plus an explicit `DATABASE_URL` override.
3. **The app honors `READER_PORT`** only insofar as uvicorn is passed
   `--port ${READER_PORT}`; the app itself need not read it.
4. **`reader` is not yet a declared package** in `backend/pyproject.toml`
   (`[tool.setuptools].packages = ["app", "cli"]`). The Containerfile therefore
   `COPY`s the `reader` directory and sets `PYTHONPATH=/app` instead of relying
   on `pip install .` to install it. If `reader` is later added to that
   `packages` list, the `COPY reader ./reader` + `PYTHONPATH` lines can be
   dropped in favor of the plain install. `reader/` currently has no
   `__init__.py`; `reader.main` still imports as an implicit namespace package,
   but adding one is fine and is required if `reader` becomes a declared
   setuptools package.
5. **Migrations are applied separately** (`sms-ingest-admin migrate`) against the
   same `DATABASE_URL`; the reader image does not run migrations on start.

If the entrypoint differs from the above, update `CMD` in the `Containerfile`
and the corresponding note here.

## Cloud deployment (not in v1)

The reader is **not** deployed to the cloud, and the local packaging here is not
a cloud deployment path. If it is ever exposed:

- It would be a **separate** service from the ingest backend, scaled to zero and
  brought up on demand rather than running always-on.
- Loopback binding would no longer be the access boundary, so it would require
  real authentication plus TLS before exposure, and the same sanitized read
  auditing as local.

Do not stand up a cloud instance of the reader as part of local packaging work.
