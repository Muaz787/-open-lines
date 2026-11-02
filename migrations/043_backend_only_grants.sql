-- 043 — tables and functions in public are for the backend only
--
-- The backend and admin pages use the service role. Browsers use the public key only
-- for Supabase Auth, which these grants don't affect. Supabase's default privileges
-- still gave anon and authenticated full table privileges, kept off only by RLS with
-- no policies. This removes those privileges, so RLS is a second layer, not the only one.
--
-- Default privileges for anything postgres creates later:
--   * In public, new tables, sequences and functions no longer go to anon or
--     authenticated. service_role keeps its default grants.
--   * PostgreSQL itself gives EXECUTE on every new function to PUBLIC, and a
--     schema-specific revoke can't remove that. So it is revoked for postgres in every
--     schema, then granted back in the extensions schema, the only other schema
--     postgres can create in, to keep extension functions callable as they are now.
--
-- Changes privileges only: no data, owners, RLS settings or function bodies. Safe to
-- run twice. It refuses to commit unless anon, authenticated and PUBLIC hold nothing in
-- public, service_role keeps every table, sequence and function, RLS is on for every
-- table, and the default privileges match the intent above.

begin;
set local lock_timeout = '3s';

revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke all on all functions in schema public from public, anon, authenticated;
grant execute on all functions in schema public to service_role;

alter default privileges for role postgres in schema public
  revoke all on tables from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke all on sequences from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke all on functions from anon, authenticated;
alter default privileges for role postgres
  revoke execute on functions from public;
alter default privileges for role postgres in schema extensions
  grant execute on functions to public;

do $$
declare
    n integer;
begin
    -- Effective privileges, so grants through PUBLIC or role membership count too.
    select count(*) into n
      from pg_class c cross join (values ('anon'), ('authenticated')) r(role)
     where c.relnamespace = 'public'::regnamespace and c.relkind in ('r', 'p', 'v', 'm', 'f')
       and (has_table_privilege(r.role, c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
            or has_any_column_privilege(r.role, c.oid, 'SELECT,INSERT,UPDATE,REFERENCES'));
    if n > 0 then
        raise exception '% table privilege(s) still reachable by anon or authenticated', n;
    end if;

    select count(*) into n
      from pg_class c cross join (values ('anon'), ('authenticated')) r(role)
     where c.relnamespace = 'public'::regnamespace and c.relkind = 'S'
       and case when c.relkind = 'S'
                then has_sequence_privilege(r.role, c.oid, 'SELECT,UPDATE,USAGE') end;
    if n > 0 then
        raise exception '% sequence privilege(s) still reachable by anon or authenticated', n;
    end if;

    select count(*) into n
      from pg_proc p cross join (values ('anon'), ('authenticated')) r(role)
     where p.pronamespace = 'public'::regnamespace
       and has_function_privilege(r.role, p.oid, 'EXECUTE');
    if n > 0 then
        raise exception '% function(s) still executable by anon or authenticated', n;
    end if;

    -- One privilege per call: a comma list passes if any one of them is held.
    select count(distinct c.oid) into n
      from pg_class c cross join unnest(array['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE',
                                              'REFERENCES', 'TRIGGER', 'MAINTAIN']) p(privilege)
     where c.relnamespace = 'public'::regnamespace and c.relkind in ('r', 'p')
       and not has_table_privilege('service_role', c.oid, p.privilege);
    if n > 0 then
        raise exception '% table(s) would lose service_role access', n;
    end if;

    select count(*) into n from pg_class c
     where c.relnamespace = 'public'::regnamespace and c.relkind = 'S'
       and case when c.relkind = 'S'
                then not (has_sequence_privilege('service_role', c.oid, 'USAGE')
                          and has_sequence_privilege('service_role', c.oid, 'SELECT')
                          and has_sequence_privilege('service_role', c.oid, 'UPDATE')) end;
    if n > 0 then
        raise exception '% sequence(s) would lose service_role access', n;
    end if;

    select count(*) into n from pg_proc p
     where p.pronamespace = 'public'::regnamespace
       and not has_function_privilege('service_role', p.oid, 'EXECUTE');
    if n > 0 then
        raise exception '% function(s) would lose service_role execute', n;
    end if;

    select count(*) into n from pg_class c
     where c.relnamespace = 'public'::regnamespace and c.relkind in ('r', 'p')
       and not c.relrowsecurity;
    if n > 0 then
        raise exception '% table(s) have RLS off', n;
    end if;

    -- postgres's default privileges: nothing for anon, authenticated or PUBLIC in
    -- public, and no PUBLIC EXECUTE except in extensions.
    select count(*) into n
      from pg_default_acl d, aclexplode(d.defaclacl) a
     where d.defaclrole = 'postgres'::regrole
       and (   (d.defaclnamespace = 'public'::regnamespace
                and a.grantee in (0, 'anon'::regrole, 'authenticated'::regrole))
            or (d.defaclnamespace not in (0, 'extensions'::regnamespace) and a.grantee = 0));
    if n > 0 then
        raise exception '% default privilege(s) still go to anon, authenticated or PUBLIC', n;
    end if;

    -- With no global row, PostgreSQL's built-in default still gives PUBLIC EXECUTE.
    if not exists (select 1 from pg_default_acl d
                    where d.defaclrole = 'postgres'::regrole and d.defaclnamespace = 0
                      and d.defaclobjtype = 'f'
                      and not exists (select 1 from aclexplode(d.defaclacl) a where a.grantee = 0)) then
        raise exception 'postgres functions would still default to PUBLIC execute';
    end if;

    -- Every privilege service_role needs on new objects, checked one by one.
    select count(*) into n
      from (values ('r', 'SELECT'), ('r', 'INSERT'), ('r', 'UPDATE'), ('r', 'DELETE'),
                   ('r', 'TRUNCATE'), ('r', 'REFERENCES'), ('r', 'TRIGGER'), ('r', 'MAINTAIN'),
                   ('S', 'SELECT'), ('S', 'UPDATE'), ('S', 'USAGE'),
                   ('f', 'EXECUTE')) want(t, privilege)
     where not exists (select 1 from pg_default_acl d, aclexplode(d.defaclacl) a
                        where d.defaclrole = 'postgres'::regrole
                          and d.defaclnamespace = 'public'::regnamespace
                          and d.defaclobjtype = want.t::"char"
                          and a.grantee = 'service_role'::regrole
                          and a.privilege_type = want.privilege);
    if n > 0 then
        raise exception 'service_role would lose % default privilege(s) on new objects in public', n;
    end if;
end $$;

notify pgrst, 'reload schema';
commit;
