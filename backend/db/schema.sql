-- Open Lines schema
-- Run once against your Supabase project (SQL editor or psql)

create table if not exists tenants (
    id                      uuid primary key default gen_random_uuid(),
    business_name           text not null,
    industry                text not null,           -- 'realtor' | 'clinic' | 'parliament'
    owner_name              text,
    whatsapp_number         text,
    website_url             text,
    twilio_subaccount_sid   text,
    twilio_auth_token       text,
    twilio_phone_number     text,
    vapi_assistant_id       text,
    pinecone_namespace      text,
    openai_vector_store_id  text,
    agent_name              text default 'Alex',
    greeting_template       text,
    qualification_fields    jsonb,
    notification_format     text,
    is_active               boolean default true,
    last_crawl_at           timestamptz,
    created_at              timestamptz default now()
);

create table if not exists leads (
    id          uuid primary key default gen_random_uuid(),
    tenant_id   uuid not null references tenants(id) on delete cascade,
    name        text,
    phone       text,
    summary     text,
    urgency     text,
    status      text default 'new',
    metadata    jsonb,
    created_at  timestamptz default now()
);

create table if not exists calls (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       uuid not null references tenants(id) on delete cascade,
    lead_id         uuid not null references leads(id) on delete cascade,
    vapi_call_id    text,
    transcript      text,
    duration_secs   int,
    created_at      timestamptz default now()
);

-- Calendar integration columns (run once, idempotent)
alter table tenants add column if not exists google_refresh_token       text;
alter table tenants add column if not exists appointment_duration_minutes int default 60;
alter table tenants add column if not exists calendar_timezone           text default 'America/Toronto';

-- Smart call routing: store pre-built system prompt + Vapi phone number ID
alter table tenants add column if not exists last_system_prompt text;
alter table tenants add column if not exists vapi_phone_number_id text;

-- Auth: link Supabase auth user to tenant
alter table tenants add column if not exists user_id uuid;
alter table tenants add column if not exists email text;

-- Stripe billing
alter table tenants add column if not exists stripe_customer_id     text;
alter table tenants add column if not exists stripe_subscription_id text;
alter table tenants add column if not exists subscription_plan      text;
alter table tenants add column if not exists subscription_status    text default 'none';

-- Knowledge base file tracking
alter table tenants add column if not exists kb_files jsonb default '[]'::jsonb;
alter table tenants add column if not exists extra_instructions text;

-- Appointments booked by the AI receptionist
create table if not exists appointments (
    id                   uuid primary key default gen_random_uuid(),
    tenant_id            uuid not null references tenants(id) on delete cascade,
    caller_name          text,
    caller_phone         text,
    service              text,
    appointment_datetime timestamptz not null,
    duration_minutes     int default 60,
    status               text default 'confirmed',  -- confirmed | cancelled | completed
    vapi_call_id         text,
    google_event_id      text,
    created_at           timestamptz default now()
);
