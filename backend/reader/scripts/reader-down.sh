#!/usr/bin/env bash
# Tear down the admin reader UI pod started by reader-up.sh.
#
# By default this removes the pod/containers but KEEPS the Postgres data
# volume (so re-running reader-up.sh preserves local data). Pass --purge to
# also delete the volume.
#
# Usage:
#   ./scripts/reader-down.sh            # stop + remove pod, keep DB volume
#   ./scripts/reader-down.sh --purge    # also delete the DB volume
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."   # backend/reader/

POD_NAME="sms-ingest-reader"
DB_VOLUME="${POD_NAME}-db-data"
PURGE="${1:-}"

if [[ -n "${PURGE}" && "${PURGE}" != "--purge" ]]; then
  echo "error: unrecognized argument '${PURGE}' (expected --purge or no argument)" >&2
  exit 1
fi

if podman pod exists "${POD_NAME}"; then
  echo "==> Removing pod ${POD_NAME}"
  podman pod rm -f "${POD_NAME}"
else
  echo "==> Pod ${POD_NAME} not running; nothing to remove"
fi

if [[ "${PURGE}" == "--purge" ]]; then
  if podman volume exists "${DB_VOLUME}"; then
    echo "==> Purging DB volume ${DB_VOLUME}"
    podman volume rm "${DB_VOLUME}"
  fi
else
  echo "==> Keeping DB volume ${DB_VOLUME} (use --purge to delete it)"
fi

echo "==> Down."
