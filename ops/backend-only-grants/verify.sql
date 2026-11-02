-- Read-only checks to run after migration 043. Every "ok" must be true. Changes nothing.
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
  'service_role_tables', (select json_build_object('ok', bool_and(has_table_privilege('service_role', oid,
        'SELECT') and has_table_privilege('service_role', oid, 'INSERT') and has_table_privilege('service_role', oid, 'UPDATE')
        and has_table_privilege('service_role', oid, 'DELETE')), 'count', count(*))
      from pg_class where relnamespace = 'public'::regnamespace and relkind in ('r', 'p')),
  'service_role_functions', (select json_build_object('ok', bool_and(has_function_privilege('service_role', oid, 'EXECUTE')), 'count', count(*))
      from pg_proc where pronamespace = 'public'::regnamespace),
  'rls_on', (select json_build_object('ok', bool_and(relrowsecurity), 'count', count(*))
      from pg_class where relnamespace = 'public'::regnamespace and relkind in ('r', 'p')),
  'postgres_default_privileges', (select json_agg(coalesce(nullif(defaclnamespace, 0)::regnamespace::text, '(global)')
        || ' ' || defaclobjtype::text || ' ' || defaclacl::text order by 1)
      from pg_default_acl where defaclrole = 'postgres'::regrole
       and defaclnamespace in (0, 'public'::regnamespace, 'extensions'::regnamespace)),
  'expected_default_privileges', json_build_object('ok', (select count(*) = 5 from pg_default_acl
       where defaclrole = 'postgres'::regrole and defaclacl::text in (
         '{postgres=X/postgres}', '{=X/postgres}', '{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}',
         '{postgres=rwU/postgres,service_role=rwU/postgres}', '{postgres=X/postgres,service_role=X/postgres}')
       and defaclnamespace in (0, 'public'::regnamespace, 'extensions'::regnamespace)))
) as r;
