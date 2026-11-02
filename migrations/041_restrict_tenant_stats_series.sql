-- 041 — tenant_stats_series is for the backend only
--
-- The function is SECURITY DEFINER, so it runs regardless of RLS. Supabase's default
-- privileges also gave EXECUTE to PUBLIC, anon and authenticated, which let anyone with
-- the public key read a tenant's counts through the API by passing its id. The backend
-- calls it with the service role after checking ownership, so nothing else needs it.
--
-- Changes permissions only: the function's body, data and owner are untouched.
-- Safe to run twice. A new function needs its own revoke, because the default
-- privileges still apply to anything created later.

begin;
set local lock_timeout = '3s';

revoke execute on function public.tenant_stats_series(uuid, timestamptz, text)
  from public, anon, authenticated;

grant execute on function public.tenant_stats_series(uuid, timestamptz, text)
  to service_role;

notify pgrst, 'reload schema';
commit;
