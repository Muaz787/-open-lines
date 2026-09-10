-- W6A2 — the durable reschedule relationship.
--
-- Slot offers and appointment refs both die with the call. If a replacement was
-- created and the original's cancellation failed, this column is the only
-- surviving evidence of that relationship, and the next call must find it rather
-- than book a third time.
--
-- ON DELETE NO ACTION, not SET NULL. SET NULL would let a delete quietly destroy
-- the very relationship recovery depends on. NO ACTION refuses to orphan a
-- replacement in the single-row case, while still permitting the tenant-wide PII
-- purge in retention.delete_tenant_data, which removes source and replacement in
-- the SAME statement -- NO ACTION is checked at end of statement, RESTRICT is
-- not deferrable and would break account deletion for any tenant who ever
-- rescheduled.

alter table appointments
    add column if not exists rescheduled_from_appointment_id uuid
    references appointments(id) on delete no action;

-- The invariant: one source appointment has at most one replacement, enforced by
-- the database rather than by careful code. A partial unique btree also serves
-- equality lookups on the column, so no second index is needed.
create unique index if not exists appointments_rescheduled_from_unique
    on appointments (rescheduled_from_appointment_id)
    where rescheduled_from_appointment_id is not null;
