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

-- Metered overage billing: track minutes consumed per billing period
alter table tenants add column if not exists minutes_used_this_period int     default 0;
alter table tenants add column if not exists overage_minutes_reported  int     default 0;
alter table tenants add column if not exists billing_period_anchor     date;

-- Vapi sub-organization per tenant (isolated 10-call concurrent limit)
alter table tenants add column if not exists vapi_suborg_id      text;
alter table tenants add column if not exists vapi_suborg_api_key text;  -- AES-256-GCM encrypted

-- Calls table: ensure transcript column exists (may be absent in older deployments)
alter table calls add column if not exists transcript text;

-- Per-tenant business hours for calendar availability (0-23, defaults to 9-17)
alter table tenants add column if not exists business_hours_start int default 9;
alter table tenants add column if not exists business_hours_end   int default 17;

-- Lead last-activity timestamp (updated whenever a lead is touched by a new call)
alter table leads add column if not exists updated_at timestamptz default now();

-- Operating days (Python weekday convention: Mon=0..Sun=6), default Mon-Fri
alter table tenants add column if not exists business_days jsonb default '[0,1,2,3,4]'::jsonb;
-- Optional daily break window (e.g. lunch); null = no break. Backend-enforced.
alter table tenants add column if not exists break_start int;
alter table tenants add column if not exists break_end   int;
-- Free-text booking guidance woven into the AI's system prompt (soft rules)
alter table tenants add column if not exists booking_instructions text;

-- Knowledge base source tracking
create table if not exists kb_entries (
    id          uuid primary key default gen_random_uuid(),
    tenant_id   uuid not null references tenants(id) on delete cascade,
    type        text not null,          -- 'file' | 'text' | 'website'
    label       text not null,          -- filename, text preview, or URL
    preview     text,                   -- first 200 chars (text entries only)
    added_at    timestamptz default now()
);

-- Durable webhook event queue (retry-safe end-of-call processing)
create table if not exists webhook_events (
    id            uuid primary key default gen_random_uuid(),
    event_type    text        not null,
    call_id       text,
    payload       jsonb       not null,
    status        text        not null default 'pending',  -- pending | done | failed
    attempts      int         not null default 0,
    last_error    text,
    next_retry_at timestamptz,
    created_at    timestamptz default now(),
    processed_at  timestamptz
);
-- Deduplicate: one event per (call_id, event_type) so Vapi retries are no-ops
create unique index if not exists webhook_events_call_dedup_idx
    on webhook_events (call_id, event_type) where call_id is not null;
create index if not exists webhook_events_pending_idx
    on webhook_events (status, next_retry_at);

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

-- ---------------------------------------------------------------------------
-- OAuth state nonces (CSRF / replay protection for provider connect flows)
-- ---------------------------------------------------------------------------
-- One row per outstanding OAuth "connect" attempt. The opaque `nonce` is sent
-- to the provider as the `state` parameter and consumed (deleted) on callback,
-- so a state is single-use, time-limited, and bound to a tenant + provider.
create table if not exists oauth_states (
    nonce       text primary key,
    tenant_id   uuid not null references tenants(id) on delete cascade,
    provider    text not null,              -- google_calendar | microsoft_calendar | hubspot | slack
    created_at  timestamptz not null default now(),
    expires_at  timestamptz not null
);
create index if not exists oauth_states_expires_idx on oauth_states (expires_at);

-- ---------------------------------------------------------------------------
-- Scheduled website re-crawl (knowledge base freshness)
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists auto_recrawl_enabled boolean default true;
alter table tenants add column if not exists last_crawl_status     text;     -- success | error
alter table tenants add column if not exists last_crawl_error      text;     -- sanitized
alter table tenants add column if not exists last_crawl_pages       int;
alter table tenants add column if not exists last_crawl_source     text;     -- manual | scheduled | onboarding
alter table tenants add column if not exists last_crawl_failures   int default 0;
alter table tenants add column if not exists next_crawl_at         timestamptz;

-- ---------------------------------------------------------------------------
-- Free-trial reminder email dedup flags
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists trial_email_day3_sent  boolean default false;
alter table tenants add column if not exists trial_email_day6_sent  boolean default false;
alter table tenants add column if not exists trial_email_ended_sent boolean default false;

-- ---------------------------------------------------------------------------
-- Structured website knowledge extraction (Business Brief)
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists business_brief         text;
alter table tenants add column if not exists extracted_services     jsonb;
alter table tenants add column if not exists extracted_faqs         jsonb;
alter table tenants add column if not exists extracted_service_areas jsonb;
alter table tenants add column if not exists extracted_policies     jsonb;

-- ---------------------------------------------------------------------------
-- Data retention: track when a tenant account was closed (for delayed purge)
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists closed_at timestamptz;
