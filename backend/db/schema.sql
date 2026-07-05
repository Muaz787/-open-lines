-- Open Lines schema
-- Run once against your Supabase project (SQL editor or psql)

create table if not exists tenants (
    id                      uuid primary key default gen_random_uuid(),
    business_name           text not null,
    industry                text not null,           -- 'realtor' | 'clinic' | 'parliament'
    owner_name              text,
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

-- ---------------------------------------------------------------------------
-- Business contact phone number (the tenant's own published line, distinct
-- from twilio_phone_number which is the AI receptionist line). Editable in
-- Settings; not captured at onboarding today, so starts null.
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists business_phone text;

-- ---------------------------------------------------------------------------
-- Call-summary notification channel preference: 'email' | 'sms' | 'both'
-- (default email). SMS summaries are sent to business_phone. WhatsApp is a
-- planned future channel. The existing email_notifications flag remains the
-- master on/off switch for call-summary notifications.
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists notification_channel text default 'email';

-- ---------------------------------------------------------------------------
-- Dedicated mobile number for SMS call-summary alerts. Kept separate from
-- business_phone (which may be a landline). Falls back to business_phone when
-- blank.
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists sms_alert_number text;

-- ---------------------------------------------------------------------------
-- Pooled booking capacity: how many appointments can run at the same time
-- (e.g. a barbershop with 4 chairs = 4). Default 1 preserves single-resource
-- behavior for every existing tenant.
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists slot_capacity int default 1;

-- ---------------------------------------------------------------------------
-- System metadata KV (e.g. daily-cron heartbeat for the admin health page).
-- ---------------------------------------------------------------------------
create table if not exists system_meta (
    key        text primary key,
    value      text,
    updated_at timestamptz default now()
);

-- ---------------------------------------------------------------------------
-- Conditional / group deposits: collect a deposit for all bookings (default) or
-- only group bookings of N+ people, optionally charged per person.
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists deposit_applies        text default 'all';   -- 'all' | 'group'
alter table tenants add column if not exists deposit_group_min_size int default 2;
alter table tenants add column if not exists deposit_per_person     boolean default false;
alter table appointments add column if not exists party_size int default 1;

-- ---------------------------------------------------------------------------
-- Named staff / resources (Phase 2). A tenant is in "staff mode" when it has
-- >= 1 active staff row — then capacity per slot = the number of active staff,
-- and each appointment is attributed to one of them (first-available, or a
-- caller-requested name). In-app schedules: staff share the shop's hours;
-- availability = those hours minus that staff member's own bookings.
-- ---------------------------------------------------------------------------
create table if not exists staff (
    id          uuid primary key default gen_random_uuid(),
    tenant_id   uuid not null references tenants(id) on delete cascade,
    name        text not null,
    is_active   boolean default true,
    created_at  timestamptz default now()
);
create index if not exists idx_staff_tenant on staff (tenant_id);

alter table appointments add column if not exists staff_id   uuid;
alter table appointments add column if not exists staff_name text;

-- ---------------------------------------------------------------------------
-- Per-channel call-summary notification toggles (replace the email_notifications
-- master switch + notification_channel enum). WhatsApp is production-only and
-- goes to sms_alert_number via an approved Twilio Content Template.
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists email_enabled    boolean default true;
alter table tenants add column if not exists sms_enabled       boolean default false;
alter table tenants add column if not exists whatsapp_enabled  boolean default false;

-- Backfill the new toggles from the old settings so existing tenants keep their
-- current behaviour (whatsapp stays off). Safe to re-run.
update tenants set
  email_enabled = (coalesce(email_notifications, false) and coalesce(notification_channel, 'email') in ('email', 'both')),
  sms_enabled   = (coalesce(email_notifications, false) and coalesce(notification_channel, 'email') in ('sms', 'both'));

-- ---------------------------------------------------------------------------
-- AI Insights v2: per-call enrichment (intent + signals) used to compute
-- evidence-based, sample-size-aware insights. Populated by the per-call
-- analysis (webhook) and a one-time backfill over existing transcripts.
-- ---------------------------------------------------------------------------
alter table calls add column if not exists intent           text;    -- sales_opportunity | existing_customer | booking_confirmation | reschedule_or_cancel | support_question | spam_or_robocall | wrong_number | delivery_or_courier | other
alter table calls add column if not exists service_topic    text;    -- short label of the main service/topic requested
alter table calls add column if not exists sentiment        text;    -- positive | neutral | negative
alter table calls add column if not exists pricing_question boolean;  -- caller asked about price/cost/fees
alter table calls add column if not exists ai_confident     boolean; -- assistant answered confidently / completed the request
alter table calls add column if not exists knowledge_gap    boolean; -- assistant could not answer something confidently
alter table calls add column if not exists gap_topic        text;    -- short label of what the assistant couldn't answer

-- Cached AI Insights payload per tenant (regenerated on demand; cache is
-- considered stale when new calls have arrived since source_call_count).
create table if not exists ai_insights (
    tenant_id         uuid primary key references tenants(id) on delete cascade,
    payload           jsonb not null,
    generated_at      timestamptz not null default now(),
    source_call_count int not null default 0
);

-- ---------------------------------------------------------------------------
-- Square Appointments (Bookings API) — P1: read availability from the
-- merchant's own Square calendar and (P2) book into it. We cache the Square
-- service catalog + team roster per tenant so the tool layer can map a spoken
-- service/staff name to the Square IDs that SearchAvailability/CreateBooking need.
--   square_appointments_enabled  -> live dispatch switch (stays OFF until P2 wires booking)
--   square_appointments_bookable -> booking_enabled from the Square booking profile (advisory)
--   square_location_timezone     -> location tz for slot display
--   square_booking_synced_at     -> last catalog/team sync
-- (square_location_id / square_currency already exist from the deposits integration.)
-- ---------------------------------------------------------------------------
alter table tenants add column if not exists square_appointments_enabled  boolean default false;
alter table tenants add column if not exists square_appointments_bookable boolean default false;
alter table tenants add column if not exists square_location_timezone     text;
alter table tenants add column if not exists square_booking_synced_at      timestamptz;

create table if not exists square_services (
    id                    uuid primary key default gen_random_uuid(),
    tenant_id             uuid not null references tenants(id) on delete cascade,
    square_variation_id   text not null,
    square_item_id        text,
    name                  text not null,
    duration_minutes      int,
    price_cents           int,
    currency              text,
    variation_version     bigint,                  -- required by CreateBooking; refresh on catalog change
    team_member_ids       text[] default '{}',
    available_for_booking boolean default true,
    active                boolean default true,
    synced_at             timestamptz default now(),
    unique (tenant_id, square_variation_id)
);
create index if not exists idx_square_services_tenant on square_services(tenant_id);

create table if not exists square_staff (
    id                    uuid primary key default gen_random_uuid(),
    tenant_id             uuid not null references tenants(id) on delete cascade,
    square_team_member_id text not null,
    display_name          text,
    active                boolean default true,
    synced_at             timestamptz default now(),
    unique (tenant_id, square_team_member_id)
);
create index if not exists idx_square_staff_tenant on square_staff(tenant_id);

-- Square Appointments P3 (two-way sync): distinguish phone-booked appointments
-- ('openlines') from bookings synced in from Square's webhook ('square' — made on
-- the merchant's website / walk-in / Square dashboard).
alter table appointments add column if not exists source text default 'openlines';

-- Admin comp controls: mark a tenant as billing-exempt (line live, no trial
-- expiry / no subscription required) from the admin dashboard. Complements the
-- BILLING_EXEMPT_TENANT_IDS env list.
alter table tenants add column if not exists billing_exempt boolean default false;

-- Drop the vestigial whatsapp_number column (never read for sending; owner
-- SMS/WhatsApp alerts use sms_alert_number). Run AFTER the code that stops
-- referencing it is deployed.
alter table tenants drop column if exists whatsapp_number;

-- Email lifecycle: CASL unsubscribe for promotional (trial) email, and a
-- once-per-tenant guard so the subscription-activation email isn't resent.
alter table tenants add column if not exists marketing_unsubscribed_at        timestamptz;
alter table tenants add column if not exists subscription_activated_email_sent boolean default false;

-- Receptionist voice: the ElevenLabs voice chosen for the agent (gender-matched
-- to the agent name; custom names use voice_gender). NULL falls back to the
-- name/gender resolver at assistant-build time.
alter table tenants add column if not exists voice_id     text;
alter table tenants add column if not exists voice_gender text default 'female';
