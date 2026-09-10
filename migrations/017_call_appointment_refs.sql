-- W6A — appointment selection safety.
--
-- cancel_appointment today takes no arguments at all: it reads the caller's
-- number, takes the earliest active appointment, and cancels it. A DANI caller
-- with a Cork consultation and a Dublin fitting loses whichever is sooner, and
-- finds out by arriving.
--
-- Same shape as call_slot_offers, for the same reason. The model names a short
-- opaque ref; every identifier the destructive operation uses comes from this
-- row rather than from anything the model said. caller_phone is NOT NULL on
-- purpose: it makes "a ref cannot resolve another caller's appointment" a
-- lookup predicate rather than a check somebody can forget to write.

create table if not exists call_appointment_refs (
    vapi_call_id         text        not null,
    appointment_ref      text        not null,
    tenant_id            uuid        not null references tenants(id)          on delete cascade,
    appointment_id       uuid        not null references appointments(id)     on delete cascade,
    caller_phone         text        not null,

    tenant_location_id   uuid        null     references tenant_locations(id) on delete set null,
    provider_location_id text        null,
    provider_booking_id  text        null,
    service              text        null,
    start_at_utc         timestamptz not null,

    expires_at           timestamptz not null,
    -- Set only once the destructive operation has been accepted AND executed.
    -- A failed provider cancellation must leave this NULL so the work stays
    -- resumable rather than looking done.
    consumed_at          timestamptz null,

    created_at           timestamptz not null default now(),

    primary key (vapi_call_id, appointment_ref)
);

create index if not exists call_appointment_refs_tenant_idx
    on call_appointment_refs (tenant_id, vapi_call_id);

create index if not exists call_appointment_refs_expires_idx
    on call_appointment_refs (expires_at);

alter table call_appointment_refs enable row level security;
