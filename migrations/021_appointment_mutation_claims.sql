-- W6A2 — global mutation ownership, keyed on the durable appointment id.
--
-- Call-scoped appointment refs (017) are SELECTION capabilities: they prove
-- which appointment a caller chose, in one call. They are not locks. Two calls
-- hold two different ref rows for one appointment, so a cancel in call A and a
-- reschedule in call B could each claim their own ref and both proceed to a
-- destructive provider mutation. UNIQUE(source_appointment_id) on 020 elects
-- between reschedules only; cancellation never touches that table.
--
-- Ownership lives in its own table rather than on appointments because two
-- full-row stale-dict writes remain in the Square WEBHOOK handler
-- (square_booking.handle_booking_event): a merchant touching the booking in
-- Square rewrites the row wholesale from a value read moments earlier. A lock
-- an external actor can silently revert is not a lock.
--
-- operation_id carries NO foreign key, deliberately. PostgREST has no
-- multi-table transaction, so an FK would force the operation row to exist
-- before the claim — inverting the lock and letting a cancel interleave. What
-- replaces it is stronger: no Square call is made until the operation row
-- exists, so a claim naming a row that does not exist PROVES no provider
-- mutation occurred and is safe to release.

create table if not exists appointment_mutation_claims (
    -- The PK is the entire global uniqueness rule: one live mutation per
    -- appointment, enforced by the database, keyed on nothing call-scoped.
    appointment_id  uuid        primary key references appointments(id) on delete cascade,
    tenant_id       uuid        not null     references tenants(id)      on delete cascade,

    operation_type  text        not null,
    -- Set from the moment a reschedule claim exists (the UUID is allocated
    -- client-side before acquisition), so there is no ambiguous NULL window.
    operation_id    uuid        null,
    -- Why reconciliation is owed. 'provider_outcome_unknown' means the cancel
    -- may or may not have landed; 'local_write_failed' means it definitely did
    -- and our own record did not follow. The recovery worker's correct action
    -- differs between them, which is why one flag would not do.
    reconcile_reason text       null,

    claim_token     uuid        not null,
    claimed_at      timestamptz not null default now(),
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),

    constraint appointment_mutation_claims_type_chk
        check (operation_type in ('cancel', 'reschedule', 'cancel_reconcile')),

    -- A reschedule claim always names its operation; the other two never do.
    constraint appointment_mutation_claims_opid_chk
        check ((operation_type = 'reschedule') = (operation_id is not null)),

    -- reconcile_reason exists exactly when reconciliation is owed, and only
    -- with a known value.
    constraint appointment_mutation_claims_reason_chk
        check (
            (operation_type = 'cancel_reconcile') = (reconcile_reason is not null)
            and (reconcile_reason is null
                 or reconcile_reason in ('provider_outcome_unknown', 'local_write_failed'))
        )
);

-- Stale-claim scans for the type-matched recovery workers.
create index if not exists appointment_mutation_claims_stale_idx
    on appointment_mutation_claims (claimed_at);

-- Find the claim belonging to a given reschedule operation during recovery.
create index if not exists appointment_mutation_claims_op_idx
    on appointment_mutation_claims (operation_id)
    where operation_id is not null;

alter table appointment_mutation_claims enable row level security;
