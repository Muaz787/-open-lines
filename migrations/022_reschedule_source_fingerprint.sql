-- W6A2 — source fingerprint, cancellation-failure discriminator, and a
-- uniqueness rule that matches the approved state semantics.
--
-- Forward migration only. 020 is applied and validated in production and is not
-- rewritten.
--
-- WHY THE FINGERPRINT
-- 020 freezes the TARGET completely so a replay is byte-identical. It holds
-- nothing about the SOURCE, so a fingerprint captured during the authoritative
-- read would die with the process and the recovery worker would be back to
-- "cancel whatever is there now" — which would destroy a merchant's own edit if
-- they moved the appointment in Square between our read and our cancel. version
-- plus start_at plus the booking id detect every material change worth acting
-- on; status and location are re-read live anyway.
--
-- WHY THE DISCRIMINATOR
-- cancel_failed meant two incompatible things: "retry the cancellation" and
-- "a merchant changed this, never cancel automatically". That ambiguity does not
-- survive a process restart, and a sweeper that guessed wrong would cancel the
-- merchant's edited booking. Three values, not two, because "retry" and
-- "reconcile provider truth first" are different actions.
--
-- WHY THE INDEX CHANGES
-- 020's unique index on source_appointment_id is TOTAL. Under the approved
-- semantics create_failed means Square definitively created nothing, the source
-- is untouched, and the caller may reschedule again later — which a total index
-- forbids forever. The partial index covers exactly the states that still own
-- the source or have already mutated the provider.

alter table appointment_reschedule_operations
    add column if not exists source_provider_booking_id text,
    add column if not exists source_booking_version     bigint,
    add column if not exists source_start_at_utc        timestamptz,
    add column if not exists cancel_failure_reason      text;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'appointment_reschedule_operations'::regclass
          and conname  = 'appointment_reschedule_ops_cancel_reason_chk'
    ) then
        alter table appointment_reschedule_operations
            add constraint appointment_reschedule_ops_cancel_reason_chk
            check (
                cancel_failure_reason is null
                or cancel_failure_reason in ('provider_retryable',
                                             'provider_unknown',
                                             'source_changed')
            );
    end if;
end $$;

-- Drop and recreate in one migration so no window exists without a uniqueness
-- rule. The table has zero rows, so nothing can violate the new predicate.
drop index if exists appointment_reschedule_ops_source_key;

create unique index if not exists appointment_reschedule_ops_live_source_key
    on appointment_reschedule_operations (source_appointment_id)
    where state in ('in_progress', 'replacement_created', 'cancel_failed');

-- Look up a source's operation history, including the create_failed rows the
-- unique index above deliberately no longer covers.
create index if not exists appointment_reschedule_ops_source_idx
    on appointment_reschedule_operations (source_appointment_id);
