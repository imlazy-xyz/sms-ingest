-- 0001_initial.sql
-- Initial schema for the SMS ingest backend (v1).
-- Contract source: projects/sms-ingest/docs/backend-plan.md (private agent repo).
--
-- Notes:
--   * Sensitive SMS fields are stored encrypted as bytea; never plaintext.
--   * Raw device tokens are never stored; only a keyed hash + short prefix.
--   * Dedupe is enforced by a DB unique constraint, not only application logic.
--   * gen_random_uuid() is built into PostgreSQL 13+ (Supabase runs 15+).

create table if not exists devices (
    id                uuid primary key default gen_random_uuid(),
    label             text        not null,
    token_prefix      text        not null,
    token_hash        text        not null unique,
    dedupe_secret_enc bytea,
    status            text        not null default 'active',
    created_at        timestamptz not null default now(),
    revoked_at        timestamptz,
    last_seen_at      timestamptz
);

create table if not exists upload_batches (
    id              uuid primary key default gen_random_uuid(),
    device_id       uuid        not null references devices (id),
    client_batch_id text        not null,
    status          text        not null,
    received_at     timestamptz not null default now(),
    accepted_count  int         not null default 0,
    duplicate_count int         not null default 0,
    rejected_count  int         not null default 0,
    error_summary   text,
    unique (device_id, client_batch_id)
);

create index if not exists idx_upload_batches_device
    on upload_batches (device_id);

create table if not exists sms_records (
    id              uuid primary key default gen_random_uuid(),
    device_id       uuid        not null references devices (id),
    upload_batch_id uuid        not null references upload_batches (id),
    dedupe_id       text        not null,
    sms_received_at timestamptz not null,
    direction       text        not null,
    sender_enc      bytea       not null,
    body_enc        bytea       not null,
    thread_hint_enc bytea,
    sim_info_enc    bytea,
    created_at      timestamptz not null default now(),
    expires_at      timestamptz not null,
    unique (device_id, dedupe_id)
);

create index if not exists idx_sms_records_expires_at
    on sms_records (expires_at);
create index if not exists idx_sms_records_device
    on sms_records (device_id);

create table if not exists audit_events (
    id          uuid primary key default gen_random_uuid(),
    event_type  text        not null,
    device_id   uuid,
    actor_type  text        not null,
    actor_id    text,
    occurred_at timestamptz not null default now(),
    metadata    jsonb       not null default '{}'::jsonb
);

create index if not exists idx_audit_events_type
    on audit_events (event_type);
create index if not exists idx_audit_events_device
    on audit_events (device_id);

create table if not exists app_config (
    key        text primary key,
    value      jsonb       not null,
    updated_at timestamptz not null default now()
);

-- Default retention: 90 days (configurable via the admin CLI).
insert into app_config (key, value)
values ('retention_days', '90'::jsonb)
on conflict (key) do nothing;
