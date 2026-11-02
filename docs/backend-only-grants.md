# Backend-only grants

Migration 043 removes every privilege that `anon` and `authenticated` hold on tables,
sequences and functions in `public`, and stops new objects from getting them. RLS stays
on for every table, so it becomes a second layer instead of the only one.

The backend and the admin pages use the service role. Browsers use the public key only
for Supabase Auth, which these grants don't affect.

## What changes

| Object | Before | After |
|---|---|---|
| Existing tables (45 of 47) | `anon` and `authenticated` hold all 8 privileges | None |
| `usage_events`, `usage_quarantine` | None | None |
| Existing functions (8) | `postgres` and `service_role` only | Unchanged |
| Sequences | None exist | None exist |
| New tables, views, sequences in `public` | `anon`, `authenticated`, `service_role` | `service_role` only |
| New functions in `public` | `PUBLIC`, `anon`, `authenticated`, `service_role` | `service_role` only |
| New functions in `extensions` | `PUBLIC` | `PUBLIC` (unchanged) |
| New functions in a new schema postgres creates | `PUBLIC` | Owner only: grant explicitly |

`service_role` keeps every privilege it has. Only objects created by `postgres` follow
these defaults. Objects created by `supabase_admin` still follow Supabase's defaults,
which `postgres` can't change; our migrations don't create objects that way.

### Why the global function default

PostgreSQL gives `PUBLIC` EXECUTE on every new function. A default set for one schema is
added to that, so it can't remove it. 043 removes it for every function `postgres`
creates, then grants it back in `extensions`, the only other schema where `postgres` can
create functions. Extensions installed with `CREATE EXTENSION` are owned by
`supabase_admin` and aren't affected.

After a request with the public key or a signed-in user's token, a table read fails with
`42501` instead of returning no rows.

## Files

| File | Purpose | Changes data |
|---|---|---|
| `migrations/preflight/043_preflight.sql` | Confirms production still matches the snapshot the rollback was built from | No |
| `migrations/043_backend_only_grants.sql` | The change. Refuses to commit unless every check passes | Privileges only |
| `ops/backend-only-grants/verify.sql` | Checks the result | No |
| `ops/backend-only-grants/rollback.sql` | Restores every removed privilege and default | Privileges only |

## Release

No code is deployed. Run each step in the SQL Editor of project `gsylobklnpytitaqcley`,
as `postgres`.

1. Run the preflight. Every `ok` must be true, including `fingerprint`. Stop otherwise:
   the rollback is exact only for the state it describes.
2. Apply 043. It aborts and changes nothing if any check fails.
3. Run `verify.sql`. Every `ok` must be true.
4. Check:
   - A REST request to `tenants` with the public key returns `42501`.
   - Dashboard sign-in, sign-out and password reset work.
   - The admin pages load, and System Health passes.
   - Backend logs show no `42501` or `permission denied`.
   - The next real call and webhook are recorded. Don't replay webhooks to test this.
5. After a day, group the API gateway logs by key type and path. There should be no
   table, RPC or GraphQL request with the public key except your own checks.

## Rollback

Run `ops/backend-only-grants/rollback.sql`, then the preflight: every `ok` should be true
again. It restores the same grantee, grantor and privileges on every table; only the
order of entries inside each ACL differs, which has no effect. Running it twice is safe.
