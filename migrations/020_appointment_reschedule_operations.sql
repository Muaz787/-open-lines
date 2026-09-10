-- W6A2 — ownership of the provider mutation, and everything needed to repeat it.
--
-- A database constraint stops a duplicate ROW. It cannot stop a duplicate Square
-- BOOKING, because the provider call happens before the insert: two workers both
-- read "no replacement", both call CreateBooking, and the unique index then
-- rejects only the second row. One row, two bookings.
--
-- So ownership is acquired BEFORE the provider call, and the claim carries the
-- target with it. An idempotency key only dedupes a request that is the same
-- logical request; if the target lives only in call_slot_offers it dies with the
-- call, and the next worker holds a key it dare not use. Every target_* value is
-- copied from a slot offer the server built from Square's own availability
-- response. None of it comes from the model.
--
-- source_appointment_id CASCADEs deliberately: the deletion audit found no
-- ordinary single-appointment DELETE path in production -- only the tenant-wide
-- PII purge -- so cascade cannot silently erase recovery state for a live
-- appointment. It fires only when the whole tenant goes.

create table if not exists appointment_reschedule_operations (
    id                               uuid        primary key default gen_random_uuid(),
    tenant_id                        uuid        not null references tenants(id)          on delete cascade,
    source_appointment_id            uuid        not null references appointments(id)     on delete cascade,
    replacement_appointment_id       uuid        null     references appointments(id)     on delete set null,

    -- The target booking snapshot: exactly what CreateBooking will be asked to
    -- make, captured before it is asked. Together with the key below this pair is
    -- immutable once the operation may have reached Square.
    target_tenant_location_id        uuid        null     references tenant_locations(id) on delete set null,
    target_provider_location_id      text        not null,
    -- Stored, not re-derived: a different customer id is a different request body,
    -- which turns replay into an idempotency conflict instead of a no-op.
    target_provider_customer_id      text        not null,
    target_service_variation_id      text        not null,
    target_service_variation_version bigint      null,
    target_team_member_id            text        not null,
    target_start_at_utc              timestamptz not null,
    target_duration_minutes          int         null,
    -- Drives customer_note, the replacement's service, and the spoken line.
    target_service_name              text        null,

    -- Never derived from claim_token, which changes on takeover.
    provider_idempotency_key         uuid        not null default gen_random_uuid(),

    claim_token                      uuid        null,
    claimed_at                       timestamptz not null default now(),
    state                            text        not null default 'in_progress',

    created_at                       timestamptz not null default now(),
    updated_at                       timestamptz not null default now(),

    -- in_progress covers both "Square not called yet" and "called, outcome
    -- unknown". Both have the identical safe action -- replay the stored payload
    -- with the stored key -- so a state distinguishing them would change nothing.
    constraint appointment_reschedule_ops_state_chk check (state in (
        'in_progress', 'create_failed', 'replacement_created', 'cancel_failed', 'completed'
    )),
    constraint appointment_reschedule_ops_not_self_chk check (
        replacement_appointment_id is null
        or replacement_appointment_id <> source_appointment_id
    )
);

-- The authorization boundary: one worker per source appointment, elected by the
-- database before anyone is allowed to call Square.
create unique index if not exists appointment_reschedule_ops_source_key
    on appointment_reschedule_operations (source_appointment_id);

-- Discoverable-for-recovery. replacement_created is included because it is NOT
-- terminal: a crash after the replacement persists but before the source is
-- cancelled leaves real work undone, and it must be findable without waiting for
-- the caller to ring back. create_failed and completed are excluded on purpose --
-- neither has outstanding provider work.
create index if not exists appointment_reschedule_ops_unfinished_idx
    on appointment_reschedule_operations (claimed_at)
    where state in ('in_progress', 'replacement_created', 'cancel_failed');

alter table appointment_reschedule_operations enable row level security;
