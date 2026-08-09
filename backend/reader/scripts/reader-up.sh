#!/usr/bin/env bash
# Bring up the admin reader UI + a local Postgres, loopback-only, via Podman.
#
# This script is the SOURCE OF TRUTH for the loopback-only guarantee — not
# reader-pod.yaml. `podman kube play` support for ports[].hostIP varies by
# podman version, so instead of trusting the YAML's hostIP field we publish
# ports explicitly here with `-p 127.0.0.1:<port>:<port>`, which is
# unambiguous on any podman version.
#
# Usage:
#   cd backend/reader
#   cp ../.env.example .env   # fill in real values; .env is gitignored
#   ./scripts/reader-up.sh
#
# Then: http://127.0.0.1:8081
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."   # backend/reader/

POD_NAME="sms-ingest-reader"
DB_CONTAINER="${POD_NAME}-db"
READER_CONTAINER="${POD_NAME}-app"
DB_VOLUME="${POD_NAME}-db-data"
READER_PORT="${READER_PORT:-8081}"
DB_PORT="${DB_PORT:-5433}"   # not 5432, to avoid colliding with infra/docker-compose.yml's ingest-dev DB
IMAGE_TAG="sms-ingest-reader:local"
ENV_FILE="${ENV_FILE:-.env}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "error: ${ENV_FILE} not found. Copy ../.env.example to ${ENV_FILE} and fill in real values first." >&2
  exit 1
fi

if ! podman image exists "${IMAGE_TAG}"; then
  cat >&2 <<EOF
error: image ${IMAGE_TAG} not found locally.

Build it (build context is backend/, not backend/reader/):
  podman build -f reader/Containerfile -t ${IMAGE_TAG} .

If building inside a nested/rootless sandbox fails, build on a host/CI runner
with a working container engine and bring the image in with
'podman save' + 'podman load' instead.
EOF
  exit 1
fi

echo "==> Creating pod ${POD_NAME} (loopback-only: 127.0.0.1:${READER_PORT}, 127.0.0.1:${DB_PORT})"
podman pod exists "${POD_NAME}" && podman pod rm -f "${POD_NAME}" >/dev/null
podman pod create \
  --name "${POD_NAME}" \
  -p "127.0.0.1:${READER_PORT}:${READER_PORT}" \
  -p "127.0.0.1:${DB_PORT}:5432"

echo "==> Starting Postgres (${DB_CONTAINER})"
podman volume exists "${DB_VOLUME}" || podman volume create "${DB_VOLUME}" >/dev/null
podman run -d --pod "${POD_NAME}" --name "${DB_CONTAINER}" \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=sms_ingest \
  -v "${DB_VOLUME}:/var/lib/postgresql/data" \
  docker.io/library/postgres:16-alpine

echo "==> Waiting for Postgres to accept connections"
for _ in $(seq 1 30); do
  if podman exec "${DB_CONTAINER}" pg_isready -U postgres >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "==> Starting reader (${READER_CONTAINER})"
# DATABASE_URL points at 127.0.0.1:5432 because reader/db share the pod's
# network namespace — Postgres's *in-pod* port is always 5432 regardless of
# which host port ${DB_PORT} publishes it on.
podman run -d --pod "${POD_NAME}" --name "${READER_CONTAINER}" \
  --env-file "${ENV_FILE}" \
  -e DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/sms_ingest" \
  -e READER_PORT="${READER_PORT}" \
  "${IMAGE_TAG}"

echo "==> Up. Reader: http://127.0.0.1:${READER_PORT}  (Postgres: 127.0.0.1:${DB_PORT}, loopback only)"
echo "    Tear down with: ./scripts/reader-down.sh"
