#!/usr/bin/env bash
# Deterministic, idempotent Supabase environment prep for sms-ingest.
# Safe to re-run; each step converges to the same state.
#
# Driven entirely by the Supabase Management API (no MCP, no DB password).
# Requires in the environment (never commit these):
#   SUPABASE_ACCESS_TOKEN   revocable Personal Access Token
#   SUPABASE_PROJECT_REF    target project ref (scopes blast radius to one project)
#
# Steps:
#   1. Drop `public` from the PostgREST exposed schemas -> closes the anon Data API.
#   2. Apply backend/migrations/*.sql (idempotent; read from disk).
#   3. Enable row-level security on every public table (deny-by-default for anon;
#      the table-owner `postgres` role bypasses RLS, so the backend is unaffected).
#   4. Verify and print the resulting state.
set -euo pipefail

: "${SUPABASE_ACCESS_TOKEN:?set SUPABASE_ACCESS_TOKEN (revocable PAT)}"
: "${SUPABASE_PROJECT_REF:?set SUPABASE_PROJECT_REF}"

API="https://api.supabase.com/v1/projects/${SUPABASE_PROJECT_REF}"
AUTH=(-H "Authorization: Bearer ${SUPABASE_ACCESS_TOKEN}" -H "Content-Type: application/json")
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIGRATIONS_DIR="${REPO_ROOT}/backend/migrations"

log() { printf '\n=== %s ===\n' "$*"; }

# run_sql <sql> -> prints the JSON result rows
run_sql() {
  curl -fsS "${AUTH[@]}" -X POST "${API}/database/query" \
    -d "$(jq -n --arg q "$1" '{query: $q}')"
}

log "1/4 Close anon Data API (drop 'public' from exposed schemas)"
echo "-- current PostgREST config:"
curl -fsS "${AUTH[@]}" "${API}/postgrest" | jq -r '.db_schema'
curl -fsS "${AUTH[@]}" -X PATCH "${API}/postgrest" -d '{"db_schema": "graphql_public"}' >/dev/null

log "2/4 Apply migrations"
shopt -s nullglob
for f in "${MIGRATIONS_DIR}"/*.sql; do
  echo "-- applying $(basename "$f")"
  run_sql "$(cat "$f")" >/dev/null
done

log "3/4 Enable RLS + restrictive deny-all on all public tables"
# RLS + a RESTRICTIVE deny-all per table. Restrictive policies are AND-combined,
# so no future permissive policy can silently re-grant access (a permissive
# deny-all would be OR-combined and thus overridable). The owner `postgres` role
# bypasses RLS, so the backend's DATABASE_URL connection is unaffected; this only
# hard-denies the anon/authenticated roles. Clears the rls_enabled_no_policy
# advisory by encoding the intentional deny as an enforced invariant.
run_sql "$(cat <<'SQL'
do $$
declare r record;
begin
  for r in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table public.%I enable row level security;', r.tablename);
    execute format('drop policy if exists deny_all on public.%I;', r.tablename);
    execute format(
      'create policy deny_all on public.%I as restrictive for all to public using (false) with check (false);',
      r.tablename);
  end loop;
end $$;
SQL
)" >/dev/null

log "4/4 Verify"
echo "-- exposed schemas (expect: graphql_public):"
curl -fsS "${AUTH[@]}" "${API}/postgrest" | jq -r '.db_schema'
echo "-- RLS per table (expect rowsecurity=true):"
run_sql "select tablename, rowsecurity
         from pg_tables where schemaname = 'public' order by tablename;" | jq -c '.'
echo "-- deny-all policy per table (expect one deny_all, permissive=RESTRICTIVE):"
run_sql "select tablename, policyname, permissive
         from pg_policies where schemaname = 'public' order by tablename;" | jq -c '.'

log "Done: Supabase environment prepared."
