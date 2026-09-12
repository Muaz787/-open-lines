-- Migration: 030 — creation claims for regulatory provider resources (W9H-QA.4)
-- PROPOSED. NOT APPLIED ANYWHERE.
--
-- ORDERING: 030 is independent of 029. They touch different tables and neither
-- reads the other's columns, so either may be applied first. 029 is authorisation
-- (what the customer agreed to); this is provider-resource ownership (who may spend
-- a Twilio resource). They are deliberately NOT combined: mixing unrelated state
-- into one migration makes both harder to review and impossible to roll back apart.
--
-- SAFETY: ADDITIVE, IDEMPOTENT, DARK. One new table. No backfill. Nothing existing
-- is altered or dropped. RLS on, no policies, matching every other regulatory table.
--
-- ── WHY THIS EXISTS ───────────────────────────────────────────────────────
-- W9H-QA.3 fixed the same defect for Twilio Addresses: two processes both reached
-- Address.create before either owned the database row, so two provider Addresses
-- existed and one was orphaned. That fix needed no schema, because an address row
-- already existed to act as the claim.
--
-- W9H.1A found the identical shape in three more places -- EndUser,
-- SupportingDocument and Bundle -- and here there is no such row:
--
--   EndUser is SHARED across every profile of a tenant for one country and
--     end-user type. Nothing in the schema is unique on that scope. The nearest
--     candidate, tenant_regulatory_business_details, is unique on exactly
--     (tenant, country, end_user_type) -- and was rejected. It holds the
--     CUSTOMER'S OWN FACTS. Putting provider lifecycle state in it would mean a
--     customer correcting their address could disturb provider ownership, would
--     entangle it with the 029 authorisation fingerprint computed over those same
--     facts, and would make the flow's hottest merge-writer also the arbiter of
--     who may call Twilio. Right uniqueness, wrong meaning.
--
--   SupportingDocument and Bundle DO have a natural row (the address, the
--     profile), and `supporting_document_sid IS NULL` / `bundle_sid IS NULL` make
--     perfectly good FENCES for attachment. What neither has is a way to say
--     "somebody is creating one RIGHT NOW" -- and a NULL SID cannot say that. A
--     lease could be squeezed into their shared updated_at, but that column is
--     written by unrelated steps, so a claim would appear to expire because some
--     other part of the workflow touched the row. Sentinel values in a column
--     named *_sid were considered and rejected: a non-SID in a SID column is the
--     kind of cleverness that causes an incident later.
--
-- One small table serves all three, with the same discipline the Address fix
-- proved: claim in the database first, carry the claim id to the provider in
-- FriendlyName, attach through a fenced compare-and-set.

create table if not exists tenant_regulatory_provider_claims (
    id         uuid primary key default gen_random_uuid(),
    tenant_id  uuid not null references tenants(id) on delete cascade,
    provider   text not null default 'twilio',

    -- WHICH KIND of provider resource this claim is for.
    resource   text not null,

    -- THE LOGICAL SCOPE, as text, resource-specific and deterministic:
    --   end_user            '<ISO>:<end_user_type>'   e.g. 'IE:business'
    --   supporting_document '<address_row_id>:<document_type>'
    --   bundle              '<profile_id>'
    -- Text rather than a set of typed columns because the three scopes have
    -- genuinely different shapes, and three sets of mostly-NULL columns would
    -- express that worse. It is never parsed back apart -- it is only ever
    -- compared -- so it carries no meaning the application has to re-derive.
    -- NEVER customer data: an id or an enum, never a name, address or email.
    scope_key  text not null,

    provider_account_sid text null,     -- identity metadata. NEVER a token.

    -- Written ONCE, through a fence. NULL means no provider resource is attached
    -- to this claim yet -- which, unlike a NULL on a shared row, is unambiguous
    -- here, because this row exists only to answer that question.
    provider_sid text null,

    -- THE LEASE CLOCK. Its own column precisely so no unrelated step can renew or
    -- expire a claim as a side effect. Renewed in the same statement that awards a
    -- takeover, which is what stops two waiting workers both taking over.
    claimed_at timestamptz not null default now(),

    -- A terminal provider refusal, so a corrected retry can take the claim
    -- immediately instead of waiting out the stale window.
    failure text null,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    constraint trpc_provider_chk check (provider in ('twilio')),
    constraint trpc_resource_chk check
        (resource in ('end_user', 'supporting_document', 'bundle')),
    constraint trpc_scope_chk check (length(btrim(scope_key)) > 0),
    -- A claim that names a provider resource must name the account holding it: a
    -- SID is meaningless without its account (W9C proved regulatory objects are
    -- account-scoped). Mirrors tra_validated_identity_chk in 027.
    constraint trpc_sid_account_chk check
        (provider_sid is null or provider_account_sid is not null),
    constraint trpc_tenant_id_id_key unique (tenant_id, id)
);

-- THE CLAIM ITSELF. One owner per logical scope -- this index is what decides,
-- inside the database and before any provider call, which request may spend a
-- provider resource.
create unique index if not exists trpc_scope_key
    on tenant_regulatory_provider_claims (tenant_id, provider, resource, scope_key);

-- A provider SID belongs to at most one claim, within the account that holds it.
-- Account-scoped rather than global for the same reason as tra_address_sid_key:
-- that is the provider's actual namespace.
create unique index if not exists trpc_provider_sid_key
    on tenant_regulatory_provider_claims (provider, provider_account_sid, provider_sid)
    where provider_sid is not null;

alter table tenant_regulatory_provider_claims enable row level security;

comment on table tenant_regulatory_provider_claims is
    'Creation ownership for Twilio regulatory resources. A row is taken BEFORE the provider is called, so a concurrent request cannot also create one. See W9H-QA.3 (Addresses) for the measured defect this prevents.';
comment on column tenant_regulatory_provider_claims.scope_key is
    'Deterministic logical scope. Ids and enums only -- never a business name, address or email.';
comment on column tenant_regulatory_provider_claims.claimed_at is
    'Lease clock. Its own column so no unrelated write can renew or expire a claim as a side effect.';

-- ── WHAT THE APPLICATION DOES WITH THIS (not part of the DDL) ─────────────
--   1. INSERT the claim. 23505 means another request owns it: re-read, wait
--      briefly, reuse. It is never an error the caller sees.
--   2. Ask the PROVIDER whether a resource already carries this claim's marker
--      (ol:<resource>:<claim id> in FriendlyName). Exactly one -> adopt. More than
--      one -> fail closed as a provider identity conflict; never pick one.
--   3. Only the claim's owner calls create. A taken-over claim is one whose
--      claimed_at is older than the stale window, or which holds a terminal
--      failure.
--   4. Attach the SID through a compare-and-set fenced on provider_sid IS NULL.
--      A worker that lost the claim gets nothing back, and withdraws its own
--      provider resource rather than orphaning it.
--   5. An ambiguous create (timeout, 5xx) is NEVER retried blindly -- step 2
--      answers what actually happened.
--
-- Measured provider facts this depends on (W9H-QA.4, live):
--   * FriendlyName max 255 on EndUser/SupportingDocument/Bundle; the marker is 43.
--   * Bundle.list filters FriendlyName server-side; EndUser.list and
--     SupportingDocument.list do NOT -- they are matched client-side over a list
--     that holds a handful of rows per sub-account.
--   * Twilio deduplicates NONE of them, so our claim is the only protection.
--
-- ===========================================================================
-- ROLLBACK (do NOT run unless reverting). Dropping this loses the record of which
-- provider resource belongs to which claim, which is what makes a duplicate
-- recoverable. An application rollback does not need it: the table is additive and
-- a pre-W9H-QA.4 build never reads it.
-- ===========================================================================
-- drop index if exists trpc_provider_sid_key;
-- drop index if exists trpc_scope_key;
-- drop table if exists tenant_regulatory_provider_claims;
