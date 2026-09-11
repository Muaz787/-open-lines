-- W7B — durable observability for provider webhook deliveries.
--
-- WHY NOT webhook_events
-- webhook_events is a WORK QUEUE: rows are claimed, retried and marked done by
-- the background processor, and its dedup index is (call_id, event_type) where
-- call_id is not null -- shaped for Vapi calls. This table is a LEDGER: nothing
-- consumes it, rows are never claimed, and the natural key is the provider's own
-- event id. Putting a ledger in a queue would muddle the _dispatch contract C4
-- just finished cleaning up, and would make "pending" mean two different things.
--
-- ONE ROW PER LOGICAL EVENT, NOT PER DELIVERY
-- Square retries a delivery until it gets a 2xx, so the same event_id can arrive
-- many times. What we want to see is "this event arrived 4 times", not four rows
-- that have to be re-aggregated later. delivery_count + last_received_at carry
-- that, and the unique key below is what makes the increment safe.
--
-- WHAT IS DELIBERATELY NOT STORED
-- No access tokens. No customer names or phone numbers. A Square booking envelope
-- carries customer_id (an opaque provider handle) and no contact details, so the
-- extracted columns below hold identifiers only.
--
-- raw_envelope EXISTS FOR ONE PURPOSE AND IS OFF BY DEFAULT
-- W7's design rests on booking.* webhooks carrying data.object.booking.location_id.
-- That is inferred from the Booking object shape read live from the API, not from
-- an observed webhook envelope -- no production webhook has ever been captured.
-- raw_envelope lets ONE real envelope be recorded to settle that, gated on the
-- SQUARE_WEBHOOK_CAPTURE_RAW env flag and restricted in code to booking.* events.
-- Turn it off once confirmed and clear the column; see the retention note below.

create table if not exists provider_webhook_events (
    id                          uuid        primary key default gen_random_uuid(),

    provider                    text        not null,
    provider_event_id           text        not null,
    event_type                  text        not null,

    -- Claimed by the (signature-verified) payload. Recorded, never trusted as a
    -- routing decision on its own -- that is exactly the W7 rule.
    merchant_id                 text        null,
    object_type                 text        null,   -- Square's data.type
    object_id                   text        null,   -- Square's data.id
    provider_location_id        text        null,
    provider_version            bigint      null,
    provider_status             text        null,
    provider_updated_at         timestamptz null,

    -- What W7A's resolver WOULD have decided. Shadow only in W7B: nothing reads
    -- these to choose what the legacy handler mutates.
    resolution                  text        null,
    resolution_detail           text        null,
    merchant_status             text        null,
    resolved_tenant_id          uuid        null references tenants(id)          on delete set null,
    resolved_tenant_location_id uuid        null references tenant_locations(id) on delete set null,

    -- What the existing handler actually did, recorded around the dispatch.
    legacy_result               text        null,
    last_error                  text        null,

    raw_envelope                jsonb       null,

    delivery_count              int         not null default 1,
    first_received_at           timestamptz not null default now(),
    last_received_at            timestamptz not null default now(),
    created_at                  timestamptz not null default now(),
    updated_at                  timestamptz not null default now(),

    constraint provider_webhook_events_provider_chk
        check (provider in ('square')),
    constraint provider_webhook_events_delivery_count_chk
        check (delivery_count >= 1)
);

-- THE natural key. It is what makes the atomic upsert below correct, and it is
-- the only thing standing between "this arrived twice" and two half-filled rows.
create unique index if not exists provider_webhook_events_provider_event_key
    on provider_webhook_events (provider, provider_event_id);

-- Operator triage: the unresolved ones, newest first.
create index if not exists provider_webhook_events_resolution_idx
    on provider_webhook_events (resolution, last_received_at desc)
    where resolution is not null and resolution <> 'resolved';

-- Retention sweeps and "what has Square sent us lately".
create index if not exists provider_webhook_events_received_idx
    on provider_webhook_events (last_received_at desc);

-- Find every delivery touching one provider object (a booking's whole history).
create index if not exists provider_webhook_events_object_idx
    on provider_webhook_events (provider, object_id)
    where object_id is not null;

alter table provider_webhook_events enable row level security;


-- ---------------------------------------------------------------------------
-- Atomic record-or-increment.
--
-- PostgREST cannot express `delivery_count = delivery_count + 1`, and a
-- read-then-write from the application would lose increments and could turn two
-- simultaneous Square deliveries into a 23505 -- which would become a 500, which
-- would make Square retry, which would make it worse. One statement with
-- ON CONFLICT DO UPDATE removes the race entirely.
--
-- On a REPEAT delivery only the delivery counters move. The first delivery's
-- extracted metadata and shadow resolution are left alone on purpose: they are
-- the evidence of what arrived first, and a later identical delivery has nothing
-- new to say. Shadow resolution is written by a separate call.
-- ---------------------------------------------------------------------------
create or replace function record_provider_webhook_event(
    p_provider             text,
    p_provider_event_id    text,
    p_event_type           text,
    p_merchant_id          text default null,
    p_object_type          text default null,
    p_object_id            text default null,
    p_provider_location_id text default null,
    p_provider_version     bigint default null,
    p_provider_status      text default null,
    p_provider_updated_at  timestamptz default null,
    p_raw_envelope         jsonb default null
) returns provider_webhook_events
language plpgsql
security definer
set search_path = public
as $$
declare
    result provider_webhook_events;
begin
    insert into provider_webhook_events (
        provider, provider_event_id, event_type, merchant_id, object_type,
        object_id, provider_location_id, provider_version, provider_status,
        provider_updated_at, raw_envelope
    ) values (
        p_provider, p_provider_event_id, p_event_type, p_merchant_id, p_object_type,
        p_object_id, p_provider_location_id, p_provider_version, p_provider_status,
        p_provider_updated_at, p_raw_envelope
    )
    on conflict (provider, provider_event_id) do update
        set delivery_count   = provider_webhook_events.delivery_count + 1,
            last_received_at = now(),
            updated_at       = now()
    returning * into result;

    return result;
end;
$$;

-- Server-internal only. PostgREST would otherwise expose /rpc/ to any role that
-- can execute it.
revoke all on function record_provider_webhook_event(
    text, text, text, text, text, text, text, bigint, text, timestamptz, jsonb
) from public;
revoke all on function record_provider_webhook_event(
    text, text, text, text, text, text, text, bigint, text, timestamptz, jsonb
) from anon, authenticated;
grant execute on function record_provider_webhook_event(
    text, text, text, text, text, text, text, bigint, text, timestamptz, jsonb
) to service_role;


-- ===========================================================================
-- RETENTION (documented, not automated in W7B)
--
--   raw_envelope      clear as soon as the booking envelope shape is confirmed:
--                       update provider_webhook_events set raw_envelope = null;
--                     and unset SQUARE_WEBHOOK_CAPTURE_RAW.
--   metadata rows     30-90 days is ample; nothing depends on them beyond triage:
--                       delete from provider_webhook_events
--                        where last_received_at < now() - interval '90 days';
--
-- Deliberately no sweeper job: W7B adds an observation ledger, and inventing an
-- archival system around it before anyone has read it would be building for a
-- need nobody has demonstrated.
-- ===========================================================================

-- ===========================================================================
-- ROLLBACK (do NOT run unless reverting).
-- ===========================================================================
-- drop function if exists record_provider_webhook_event(
--     text, text, text, text, text, text, text, bigint, text, timestamptz, jsonb);
-- drop table if exists provider_webhook_events;
