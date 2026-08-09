-- 0002_ownership.sql
-- Read-side ownership model: users, numbers, sim_assignments, plus a stamped
-- owner_number_id column on sms_records. Additive only; never drop.
--
-- Notes:
--   * numbers.e164 is cleartext (operator's own numbers; low count).
--   * sim_assignments is interval-versioned: exactly one open row
--     (effective_to IS NULL) per (device_id, sub_id) at a time.
--   * owner_number_id is nullable and populated only by the resolution
--     command (backend/cli), never at ingestion time.

create table if not exists users (
    id           uuid primary key default gen_random_uuid(),
    display_name text        not null,
    created_at   timestamptz not null default now()
);

create table if not exists numbers (
    id         uuid primary key default gen_random_uuid(),
    e164       text        not null unique,
    label      text,
    iccid      text,
    user_id    uuid        not null references users (id),
    created_at timestamptz not null default now()
);

create index if not exists idx_numbers_user
    on numbers (user_id);

create table if not exists sim_assignments (
    id              uuid primary key default gen_random_uuid(),
    device_id       uuid        not null references devices (id),
    sub_id          int         not null,
    iccid           text,
    number_id       uuid        not null references numbers (id),
    effective_from  timestamptz not null default now(),
    effective_to    timestamptz,
    created_at      timestamptz not null default now()
);

-- Exactly one current assignment per (device, subId).
create unique index if not exists idx_sim_assignments_current
    on sim_assignments (device_id, sub_id)
    where effective_to is null;

create index if not exists idx_sim_assignments_device
    on sim_assignments (device_id);
create index if not exists idx_sim_assignments_number
    on sim_assignments (number_id);

alter table sms_records
    add column if not exists owner_number_id uuid references numbers (id);

create index if not exists idx_sms_records_owner_number
    on sms_records (owner_number_id, sms_received_at);
