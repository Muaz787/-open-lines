-- Rollback for migration 043. Restores the privileges it removed, exactly as they were
-- in the production snapshot taken 2026-11-02T14:15:38.902891+00:00:
--   * 45 tables granted to anon and 45 to authenticated, each with
--     SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER and MAINTAIN,
--     granted by postgres. usage_events and usage_quarantine had none, and still don't.
--   * postgres's default privileges: public tables, sequences and functions for anon
--     and authenticated; no global function entry (PostgreSQL's built-in PUBLIC
--     EXECUTE); no entry for the extensions schema.
-- Not touched, because 043 left them as they were: function ACLs (postgres and
-- service_role only), service_role's grants, and sequences (public has none).
-- Run as postgres. Safe to run twice.

begin;
set local lock_timeout = '3s';

grant insert, select, update, delete, truncate, references, trigger, maintain on table public."admin_audit_logs" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."admin_audit_logs" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."admin_users" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."admin_users" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."ai_insights" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."ai_insights" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."appointment_mutation_claims" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."appointment_mutation_claims" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."appointment_reschedule_operations" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."appointment_reschedule_operations" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."appointments" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."appointments" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."call_appointment_refs" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."call_appointment_refs" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."call_handling_profiles" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."call_handling_profiles" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."call_location_state" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."call_location_state" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."call_slot_offers" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."call_slot_offers" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."callback_requests" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."callback_requests" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."calls" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."calls" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."ireland_pilot_onboarding_grants" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."ireland_pilot_onboarding_grants" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."ireland_temporary_access" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."ireland_temporary_access" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."kb_entries" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."kb_entries" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."leads" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."leads" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."location_provider_bindings" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."location_provider_bindings" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."oauth_states" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."oauth_states" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."onboarding_payment_sessions" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."onboarding_payment_sessions" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."payment_short_links" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."payment_short_links" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."payments" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."payments" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."provider_customers" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."provider_customers" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."provider_webhook_events" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."provider_webhook_events" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."routing_decisions" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."routing_decisions" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."routing_destinations" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."routing_destinations" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."routing_rules" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."routing_rules" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."square_services" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."square_services" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."square_staff" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."square_staff" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."staff" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."staff" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."stripe_accounts" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."stripe_accounts" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."stripe_webhook_events" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."stripe_webhook_events" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."system_meta" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."system_meta" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenant_api_keys" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenant_api_keys" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenant_locations" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenant_locations" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenant_phone_numbers" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenant_phone_numbers" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenant_regulatory_addresses" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenant_regulatory_addresses" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenant_regulatory_authorizations" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenant_regulatory_authorizations" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenant_regulatory_business_details" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenant_regulatory_business_details" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenant_regulatory_events" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenant_regulatory_events" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenant_regulatory_profiles" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenant_regulatory_profiles" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenant_regulatory_provider_claims" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenant_regulatory_provider_claims" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenants" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."tenants" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."transfer_attempts" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."transfer_attempts" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."webhook_events" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."webhook_events" to authenticated;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."zapier_subscriptions" to anon;
grant insert, select, update, delete, truncate, references, trigger, maintain on table public."zapier_subscriptions" to authenticated;

alter default privileges for role postgres in schema public grant all on tables to anon, authenticated;
alter default privileges for role postgres in schema public grant all on sequences to anon, authenticated;
alter default privileges for role postgres in schema public grant all on functions to anon, authenticated;
alter default privileges for role postgres grant execute on functions to public;
alter default privileges for role postgres in schema extensions revoke execute on functions from public;

do $$
declare
    n integer;
begin
    select count(*) into n
      from pg_class c, aclexplode(c.relacl) a
     where c.relnamespace = 'public'::regnamespace
       and a.grantee in ('anon'::regrole, 'authenticated'::regrole);
    if n <> 720 then
        raise exception 'expected 720 table privileges for anon and authenticated, found %', n;
    end if;
    if exists (select 1 from pg_default_acl where defaclrole = 'postgres'::regrole
                and (defaclnamespace = 0 or defaclnamespace = 'extensions'::regnamespace)) then
        raise exception 'postgres still has a global or extensions default privilege entry';
    end if;
end $$;

notify pgrst, 'reload schema';
commit;
