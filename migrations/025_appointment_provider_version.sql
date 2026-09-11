-- W7D — remember which version of the provider's booking a local row reflects.
--
-- WHY THIS IS NEEDED
-- Square delivers booking webhooks asynchronously, and W7C proved on real events
-- that version increments: the same disposable booking arrived as v0 (ACCEPTED)
-- and then v1 (CANCELLED_BY_SELLER). Nothing in appointments records which
-- version a row reflects, so a v7 event arriving after a v8 event would happily
-- overwrite newer truth with older truth. These two columns are what make a
-- stale webhook a no-op instead of a regression.
--
-- WHY NULLABLE, AND WHY NO BACKFILL
-- Every existing row predates provider-version tracking. There is no honest value
-- to backfill: guessing a version would be inventing provider truth, which is the
-- one thing the whole workstream refuses to do. NULL means "we have never
-- reconciled this row against an authoritative provider read", and the comparison
-- rule below treats NULL as "accept the next authoritative version", so a legacy
-- row upgrades itself the first time a real webhook touches it.
--
-- THE COMPARISON RULE THE CODE IMPLEMENTS
--   stored IS NULL            -> accept
--   incoming  >  stored       -> accept
--   incoming ==  stored       -> no-op (duplicate delivery)
--   incoming  <  stored       -> no-op (stale delivery)
-- The accept test is expressed as a single conditional UPDATE predicate so two
-- concurrent webhook workers cannot both pass a read-then-write window.
--
-- provider_updated_at is recorded for operator forensics and ordering evidence.
-- It is NOT the staleness authority: version is monotonic per booking, whereas
-- two edits within the same second can share a timestamp.

alter table appointments
    add column if not exists provider_version    bigint      null,
    add column if not exists provider_updated_at timestamptz null;

-- Webhook reconciliation looks a row up by provider booking id and then compares
-- versions. google_event_id is the provider-booking linkage for every provider
-- (the name predates Square and is deliberately NOT renamed here -- see W7D's
-- notes; renaming a load-bearing column for aesthetics is its own migration).
create index if not exists appointments_provider_version_idx
    on appointments (google_event_id, provider_version)
    where google_event_id is not null;

-- ===========================================================================
-- ROLLBACK (do NOT run unless reverting).
--
-- Note: these columns are ADDITIVE and invisible to pre-W7D code, so an
-- application rollback does NOT require dropping them -- and dropping them would
-- discard the only record of which provider version each row reflects.
-- ===========================================================================
-- drop index if exists appointments_provider_version_idx;
-- alter table appointments
--     drop column if exists provider_version,
--     drop column if exists provider_updated_at;
