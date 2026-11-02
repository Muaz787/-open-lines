-- Read-only checks to run on production before migration 043. Changes nothing.
-- Every "ok" must be true. Stop on anything else: the rollback was generated from the
-- privileges these checks describe, so it is only exact while they still hold.
-- postgres_default_privileges lists every default privilege postgres held in the
-- 2026-11-02 snapshot, by grantee, grantor and grant option.
with acl as (
  select c.relname, e.grantee, e.grantor, e.privilege_type, e.is_grantable
    from pg_class c, aclexplode(c.relacl) e
   where c.relnamespace = 'public'::regnamespace
), fp as (
  select md5(string_agg(line, E'\n' order by line)) as h from (
    select c.relname || ' ' || c.relkind::text || ' ' || coalesce((
             select string_agg(e, ',' order by e) from (
               select case when grantee = 0 then 'PUBLIC' else pg_get_userbyid(grantee) end
                      || '<' || pg_get_userbyid(grantor) || ':' || privilege_type
                      || case when is_grantable then '*' else '' end as e
                 from aclexplode(c.relacl)) z), '(default)') as line
      from pg_class c where c.relnamespace = 'public'::regnamespace and c.relkind in ('r', 'p', 'v', 'm', 'f', 'S')
    union all
    select 'fn ' || p.oid::regprocedure::text || ' ' || coalesce(p.proacl::text, '(default)')
      from pg_proc p where p.pronamespace = 'public'::regnamespace) l)
select json_build_object(
  'database', json_build_object('ok', current_database() = 'postgres' and current_user = 'postgres',
                                'db', current_database(), 'user', current_user),
  'relations', (select json_build_object('ok', count(*) = 47 and count(*) filter (where relkind = 'r') = 47
                                               and bool_and(relrowsecurity) and bool_and(relowner = 'postgres'::regrole),
                                         'count', count(*))
                  from pg_class where relnamespace = 'public'::regnamespace and relkind in ('r', 'p', 'v', 'm', 'f', 'S')),
  'browser_role_privileges', (select json_build_object('ok', count(*) = 720 and bool_and(grantor = 'postgres'::regrole)
                                                             and not bool_or(is_grantable),
                                                       'count', count(*))
                                from acl where grantee in ('anon'::regrole, 'authenticated'::regrole)),
  'public_grantee', (select json_build_object('ok', count(*) = 0, 'count', count(*)) from acl where grantee = 0),
  'tables_without_browser_grants', (select json_build_object('ok', coalesce(array_agg(relname order by relname), '{}') = array['usage_events', 'usage_quarantine']::name[],
                                                             'found', array_agg(relname order by relname))
                                      from pg_class c where c.relnamespace = 'public'::regnamespace and c.relkind = 'r'
                                       and not exists (select 1 from acl where acl.relname = c.relname and grantee = 'anon'::regrole)),
  'column_acls', (select json_build_object('ok', count(*) = 0, 'count', count(*)) from pg_attribute a join pg_class c on c.oid = a.attrelid
                   where c.relnamespace = 'public'::regnamespace and a.attacl is not null),
  'functions', (select json_build_object('ok', count(*) = 8 and bool_and(proacl::text = '{postgres=X/postgres,service_role=X/postgres}'), 'count', count(*))
                  from pg_proc where pronamespace = 'public'::regnamespace),
  'fingerprint', (select json_build_object('ok', h = '75445228a6c99895a162874a96d59c2f', 'md5', h) from fp),
  'postgres_default_privileges', (with expected(schema, type, grantee, grantor, privilege, grantable) as (values
        ('public', 'S', 'anon', 'postgres', 'SELECT', false),
        ('public', 'S', 'anon', 'postgres', 'UPDATE', false),
        ('public', 'S', 'anon', 'postgres', 'USAGE', false),
        ('public', 'S', 'authenticated', 'postgres', 'SELECT', false),
        ('public', 'S', 'authenticated', 'postgres', 'UPDATE', false),
        ('public', 'S', 'authenticated', 'postgres', 'USAGE', false),
        ('public', 'S', 'postgres', 'postgres', 'SELECT', false),
        ('public', 'S', 'postgres', 'postgres', 'UPDATE', false),
        ('public', 'S', 'postgres', 'postgres', 'USAGE', false),
        ('public', 'S', 'service_role', 'postgres', 'SELECT', false),
        ('public', 'S', 'service_role', 'postgres', 'UPDATE', false),
        ('public', 'S', 'service_role', 'postgres', 'USAGE', false),
        ('public', 'f', 'anon', 'postgres', 'EXECUTE', false),
        ('public', 'f', 'authenticated', 'postgres', 'EXECUTE', false),
        ('public', 'f', 'postgres', 'postgres', 'EXECUTE', false),
        ('public', 'f', 'service_role', 'postgres', 'EXECUTE', false),
        ('public', 'r', 'anon', 'postgres', 'DELETE', false),
        ('public', 'r', 'anon', 'postgres', 'INSERT', false),
        ('public', 'r', 'anon', 'postgres', 'MAINTAIN', false),
        ('public', 'r', 'anon', 'postgres', 'REFERENCES', false),
        ('public', 'r', 'anon', 'postgres', 'SELECT', false),
        ('public', 'r', 'anon', 'postgres', 'TRIGGER', false),
        ('public', 'r', 'anon', 'postgres', 'TRUNCATE', false),
        ('public', 'r', 'anon', 'postgres', 'UPDATE', false),
        ('public', 'r', 'authenticated', 'postgres', 'DELETE', false),
        ('public', 'r', 'authenticated', 'postgres', 'INSERT', false),
        ('public', 'r', 'authenticated', 'postgres', 'MAINTAIN', false),
        ('public', 'r', 'authenticated', 'postgres', 'REFERENCES', false),
        ('public', 'r', 'authenticated', 'postgres', 'SELECT', false),
        ('public', 'r', 'authenticated', 'postgres', 'TRIGGER', false),
        ('public', 'r', 'authenticated', 'postgres', 'TRUNCATE', false),
        ('public', 'r', 'authenticated', 'postgres', 'UPDATE', false),
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
      from diff),
  'long_transactions', (select json_build_object('ok', count(*) = 0, 'count', count(*)) from pg_stat_activity
                         where state <> 'idle' and xact_start < now() - interval '1 minute' and pid <> pg_backend_pid())
) as r;
