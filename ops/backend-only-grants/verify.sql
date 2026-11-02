-- Read-only checks to run after migration 043. Every "ok" must be true. Changes nothing.
-- postgres_default_privileges lists every default privilege postgres should hold after
-- 043, by grantee, grantor and grant option.
select json_build_object(
  'browser_roles_relations', (select json_build_object('ok', count(*) = 0, 'count', count(*))
      from pg_class c cross join (values ('anon'), ('authenticated')) r(role)
     where c.relnamespace = 'public'::regnamespace and c.relkind in ('r', 'p', 'v', 'm', 'f')
       and (has_table_privilege(r.role, c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
            or has_any_column_privilege(r.role, c.oid, 'SELECT,INSERT,UPDATE,REFERENCES'))),
  'browser_roles_sequences', (select json_build_object('ok', count(*) = 0, 'count', count(*))
      from pg_class c cross join (values ('anon'), ('authenticated')) r(role)
     where c.relnamespace = 'public'::regnamespace and c.relkind = 'S'
       and case when c.relkind = 'S' then has_sequence_privilege(r.role, c.oid, 'SELECT,UPDATE,USAGE') end),
  'browser_roles_functions', (select json_build_object('ok', count(*) = 0, 'count', count(*))
      from pg_proc p cross join (values ('anon'), ('authenticated')) r(role)
     where p.pronamespace = 'public'::regnamespace and has_function_privilege(r.role, p.oid, 'EXECUTE')),
  'service_role_tables', (select json_build_object('ok', count(*) filter (where not has_table_privilege('service_role', c.oid, p)) = 0,
        'tables', count(distinct c.oid))
      from pg_class c cross join unnest(array['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN']) p
     where c.relnamespace = 'public'::regnamespace and c.relkind in ('r', 'p')),
  'service_role_sequences', (select json_build_object('ok', count(*) filter (where not has_sequence_privilege('service_role', c.oid, p)) = 0,
        'sequences', count(distinct c.oid))
      from pg_class c cross join unnest(array['USAGE', 'SELECT', 'UPDATE']) p
     where c.relnamespace = 'public'::regnamespace and c.relkind = 'S'),
  'service_role_functions', (select json_build_object('ok', bool_and(has_function_privilege('service_role', oid, 'EXECUTE')), 'count', count(*))
      from pg_proc where pronamespace = 'public'::regnamespace),
  'rls_on', (select json_build_object('ok', bool_and(relrowsecurity), 'count', count(*))
      from pg_class where relnamespace = 'public'::regnamespace and relkind in ('r', 'p')),
  'postgres_default_privileges', (with expected(schema, type, grantee, grantor, privilege, grantable) as (values
        ('(global)', 'f', 'postgres', 'postgres', 'EXECUTE', false),
        ('extensions', 'f', 'PUBLIC', 'postgres', 'EXECUTE', false),
        ('public', 'S', 'postgres', 'postgres', 'SELECT', false),
        ('public', 'S', 'postgres', 'postgres', 'UPDATE', false),
        ('public', 'S', 'postgres', 'postgres', 'USAGE', false),
        ('public', 'S', 'service_role', 'postgres', 'SELECT', false),
        ('public', 'S', 'service_role', 'postgres', 'UPDATE', false),
        ('public', 'S', 'service_role', 'postgres', 'USAGE', false),
        ('public', 'f', 'postgres', 'postgres', 'EXECUTE', false),
        ('public', 'f', 'service_role', 'postgres', 'EXECUTE', false),
        ('public', 'r', 'postgres', 'postgres', 'DELETE', false),
        ('public', 'r', 'postgres', 'postgres', 'INSERT', false),
        ('public', 'r', 'postgres', 'postgres', 'MAINTAIN', false),
        ('public', 'r', 'postgres', 'postgres', 'REFERENCES', false),
        ('public', 'r', 'postgres', 'postgres', 'SELECT', false),
        ('public', 'r', 'postgres', 'postgres', 'TRIGGER', false),
        ('public', 'r', 'postgres', 'postgres', 'TRUNCATE', false),
        ('public', 'r', 'postgres', 'postgres', 'UPDATE', false),
        ('public', 'r', 'service_role', 'postgres', 'DELETE', false),
        ('public', 'r', 'service_role', 'postgres', 'INSERT', false),
        ('public', 'r', 'service_role', 'postgres', 'MAINTAIN', false),
        ('public', 'r', 'service_role', 'postgres', 'REFERENCES', false),
        ('public', 'r', 'service_role', 'postgres', 'SELECT', false),
        ('public', 'r', 'service_role', 'postgres', 'TRIGGER', false),
        ('public', 'r', 'service_role', 'postgres', 'TRUNCATE', false),
        ('public', 'r', 'service_role', 'postgres', 'UPDATE', false),
        ('storage', 'S', 'anon', 'postgres', 'SELECT', false),
        ('storage', 'S', 'anon', 'postgres', 'UPDATE', false),
        ('storage', 'S', 'anon', 'postgres', 'USAGE', false),
        ('storage', 'S', 'authenticated', 'postgres', 'SELECT', false),
        ('storage', 'S', 'authenticated', 'postgres', 'UPDATE', false),
        ('storage', 'S', 'authenticated', 'postgres', 'USAGE', false),
        ('storage', 'S', 'postgres', 'postgres', 'SELECT', false),
        ('storage', 'S', 'postgres', 'postgres', 'UPDATE', false),
        ('storage', 'S', 'postgres', 'postgres', 'USAGE', false),
        ('storage', 'S', 'service_role', 'postgres', 'SELECT', false),
        ('storage', 'S', 'service_role', 'postgres', 'UPDATE', false),
        ('storage', 'S', 'service_role', 'postgres', 'USAGE', false),
        ('storage', 'f', 'anon', 'postgres', 'EXECUTE', false),
        ('storage', 'f', 'authenticated', 'postgres', 'EXECUTE', false),
        ('storage', 'f', 'postgres', 'postgres', 'EXECUTE', false),
        ('storage', 'f', 'service_role', 'postgres', 'EXECUTE', false),
        ('storage', 'r', 'anon', 'postgres', 'DELETE', false),
        ('storage', 'r', 'anon', 'postgres', 'INSERT', false),
        ('storage', 'r', 'anon', 'postgres', 'MAINTAIN', false),
        ('storage', 'r', 'anon', 'postgres', 'REFERENCES', false),
        ('storage', 'r', 'anon', 'postgres', 'SELECT', false),
        ('storage', 'r', 'anon', 'postgres', 'TRIGGER', false),
        ('storage', 'r', 'anon', 'postgres', 'TRUNCATE', false),
        ('storage', 'r', 'anon', 'postgres', 'UPDATE', false),
        ('storage', 'r', 'authenticated', 'postgres', 'DELETE', false),
        ('storage', 'r', 'authenticated', 'postgres', 'INSERT', false),
        ('storage', 'r', 'authenticated', 'postgres', 'MAINTAIN', false),
        ('storage', 'r', 'authenticated', 'postgres', 'REFERENCES', false),
        ('storage', 'r', 'authenticated', 'postgres', 'SELECT', false),
        ('storage', 'r', 'authenticated', 'postgres', 'TRIGGER', false),
        ('storage', 'r', 'authenticated', 'postgres', 'TRUNCATE', false),
        ('storage', 'r', 'authenticated', 'postgres', 'UPDATE', false),
        ('storage', 'r', 'postgres', 'postgres', 'DELETE', false),
        ('storage', 'r', 'postgres', 'postgres', 'INSERT', false),
        ('storage', 'r', 'postgres', 'postgres', 'MAINTAIN', false),
        ('storage', 'r', 'postgres', 'postgres', 'REFERENCES', false),
        ('storage', 'r', 'postgres', 'postgres', 'SELECT', false),
        ('storage', 'r', 'postgres', 'postgres', 'TRIGGER', false),
        ('storage', 'r', 'postgres', 'postgres', 'TRUNCATE', false),
        ('storage', 'r', 'postgres', 'postgres', 'UPDATE', false),
        ('storage', 'r', 'service_role', 'postgres', 'DELETE', false),
        ('storage', 'r', 'service_role', 'postgres', 'INSERT', false),
        ('storage', 'r', 'service_role', 'postgres', 'MAINTAIN', false),
        ('storage', 'r', 'service_role', 'postgres', 'REFERENCES', false),
        ('storage', 'r', 'service_role', 'postgres', 'SELECT', false),
        ('storage', 'r', 'service_role', 'postgres', 'TRIGGER', false),
        ('storage', 'r', 'service_role', 'postgres', 'TRUNCATE', false),
        ('storage', 'r', 'service_role', 'postgres', 'UPDATE', false)
    ), actual as (
      select coalesce(nullif(d.defaclnamespace, 0)::regnamespace::text, '(global)'), d.defaclobjtype::text,
             case when a.grantee = 0 then 'PUBLIC' else pg_get_userbyid(a.grantee) end,
             pg_get_userbyid(a.grantor), a.privilege_type, a.is_grantable
        from pg_default_acl d, aclexplode(d.defaclacl) a
       where d.defaclrole = 'postgres'::regrole
    ), diff as (
      select 'missing' as k, * from (select * from expected except select * from actual) m
      union all select 'unexpected', * from (select * from actual except select * from expected) u)
    select json_build_object('ok', count(*) = 0, 'expected', (select count(*) from expected),
                             'differences', coalesce(json_agg(diff order by diff.schema, diff.type, diff.grantee, diff.privilege), '[]'))
      from diff)
) as r;
