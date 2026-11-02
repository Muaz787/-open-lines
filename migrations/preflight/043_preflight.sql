-- Read-only checks to run on production before migration 043. Changes nothing.
-- Every "ok" must be true. Stop on anything else: the rollback was generated from the
-- privileges these checks describe, so it is only exact while they still hold.
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
  'postgres_default_privileges', (select json_build_object('ok', count(*) = 3
        and count(*) filter (where defaclnamespace = 'public'::regnamespace) = 3
        and bool_and((select count(*) from aclexplode(defaclacl) a where a.grantee in ('anon'::regrole, 'authenticated'::regrole)) > 0),
        'rows', json_agg(coalesce(nullif(defaclnamespace, 0)::regnamespace::text, '(global)') || ' ' || defaclobjtype::text || ' ' || defaclacl::text))
     from pg_default_acl where defaclrole = 'postgres'::regrole and defaclnamespace in (0, 'public'::regnamespace, 'extensions'::regnamespace)),
  'long_transactions', (select json_build_object('ok', count(*) = 0, 'count', count(*)) from pg_stat_activity
                         where state <> 'idle' and xact_start < now() - interval '1 minute' and pid <> pg_backend_pid())
) as r;
