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
