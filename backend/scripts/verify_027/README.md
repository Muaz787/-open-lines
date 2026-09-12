# Migration 027 — real-Postgres proof harness (W9E)

The main test suite has no database: `tests/conftest.py` stubs Supabase entirely, so
`tests/test_migration_027_contract.py` can only prove that 027 **declares** its
constraints. These scripts prove the constraints **hold**, by issuing real
INSERT/UPDATE/DELETE against a real PostgreSQL server.

They are not part of `pytest` — they need a throwaway database and a `psql` binary,
and they are destructive within that database. Run them by hand when 027 or any
schema built on it changes.

## Setup

```bash
brew install postgresql@15            # keg-only; no service is started
export PGBIN=/opt/homebrew/opt/postgresql@15/bin
export SCRATCH=/tmp/w9e_pg

$PGBIN/initdb -D $SCRATCH/pgdata --locale=en_US.UTF-8 -E UTF-8 -U w9e
$PGBIN/pg_ctl -D $SCRATCH/pgdata -l $SCRATCH/pg.log \
    -o "-p 55432 -k /tmp -c listen_addresses=127.0.0.1" start
$PGBIN/psql -h 127.0.0.1 -p 55432 -U w9e -d postgres -c "create database w9e_scratch"

export W9E_DSN="postgresql://w9e@127.0.0.1:55432/w9e_scratch"
export W9E_PSQL="$PGBIN/psql"
pip install "psycopg[binary]"         # deliberately NOT in requirements.txt
```

## Baseline: replay the real migration lineage

Two bootstrap files are needed, and both exist because of defects in the *existing*
lineage, not because of 027:

1. **`bootstrap_1_roles.sql`** — Supabase ships `anon`, `authenticated` and
   `service_role`. Migrations 008, 012 and 024 name them, so plain Postgres cannot
   replay the lineage without them. Recreating them faithfully (anon holds full table
   privileges; service_role has `BYPASSRLS`) is also what makes the RLS proof mean
   anything.
2. **`bootstrap_2_legacy_columns.sql`** — `000_consolidated_schema.sql` UPDATEs
   `tenants.email_notifications` / `.notification_channel` and `011` indexes
   `.twilio_phone_number`, but none of the three is ever CREATEd: they predate the
   consolidated file. So 000 is applied, these are added, then 000 is applied **again**
   (it is written to be idempotent) so its real `create table` still defines `tenants`.

```bash
$W9E_PSQL -q "$W9E_DSN" -f bootstrap_1_roles.sql
$W9E_PSQL -q "$W9E_DSN" -f ../../../migrations/000_consolidated_schema.sql   # fails at line 297
$W9E_PSQL -q "$W9E_DSN" -f bootstrap_2_legacy_columns.sql
for f in ../../../migrations/0*.sql; do
    $W9E_PSQL -q "$W9E_DSN" -v ON_ERROR_STOP=1 -f "$f" || echo "FAIL $f"
done
```

## The proofs

| script | what it proves |
|---|---|
| `stage_c.py` | `pg_catalog` shape: tables, columns, 22 CHECKs, 6 composite FKs, 13 partial indexes, RLS flags, zero policies |
| `stage_d.py` | 47 constraint proofs — every ownership, cardinality, lifecycle and provider-identity rule, each asserting the SQLSTATE **and** the constraint name that fired |
| `stage_e.py` | delete/cascade semantics, measured not assumed |
| `stage_f.py` | RLS against real `anon` / `authenticated` / `service_role` |
| `stage_gh.py` | replay idempotency (catalog fingerprint unchanged across three applications) and rollback/legacy compatibility |
| `stage_k.py` | migration **030**'s provider-claim constraints — 19 proofs: one claim per logical scope, scopes that must not collide, cross-tenant independence, SID uniqueness within an account, cascade |
| `stage_l_race.py` | the claim is exclusive under real OS-level concurrency — four processes per resource, one winner, every loser seeing 23505 on `trpc_scope_key` |
| `stage_m_retire_race.py` | the retirement CAS under real concurrency — four processes retiring one SID yield one winner; a stale worker cannot clear a replacement; exclusivity and `trpc_sid_account_chk` survive retirement |

```bash
cd backend/scripts/verify_027
for s in stage_c stage_d stage_e stage_f stage_gh stage_k; do python $s.py; done
python stage_l_race.py parent
python stage_m_retire_race.py parent
```

Each prints `ALL PASS` / `N/N passed`, or names the failures.

## Why `stage_e.py` matters most

It is the script that caught a real defect. 027 originally used `ON DELETE SET NULL`
on the event ledger's owner columns so a deleted profile would leave a de-owned audit
row. On real Postgres that made **tenant deletion impossible**: deleting a tenant
fires the `tenant_id` FK first, nulling `tenant_id` while `regulatory_profile_id` is
still set, which trips `tre_profile_needs_tenant_chk`. Account closure and GDPR
erasure would have failed with `23514`. Both owner FKs are now `ON DELETE CASCADE`.

No amount of reading the DDL would have found that.

## Keeping the fixtures alive as the lineage moves

`stage_d.py` and `stage_e.py` were written for a 027-only lineage. Migration **028**
then added `trp_submitted_requirements_chk` — a profile past the draft states needs a
`requirements_fingerprint` — and most fixtures in both scripts are `'approved'`, so
both began failing on their own setup and 027's proofs silently stopped running.
Both now supply the fingerprint as a literal, leaving every call site and argument
tuple untouched.

That repair was made only after confirming the failure **predates** the migration
under test: replaying the lineage with 030 excluded produces the identical failure,
on the identical 028 constraint. A harness failure that a new migration actually
caused is a regression, and would be reported rather than patched over.

## Fidelity limits

* PostgREST is not reproduced — no JWT parsing, no `auth.uid()`, no request GUCs. That
  does not affect these tables: RLS is on with no policy, so the deny is total and
  happens in Postgres, below PostgREST.
* Tested on PostgreSQL 15.19. 027 uses no version-gated syntax (no column-list
  `SET NULL`, no generated columns, no `MERGE`), so behaviour is the same on 13–18.
* `anon` UPDATE/DELETE **succeed** while matching zero rows. That is how RLS filters,
  not a hole — `stage_f.py` asserts `rowcount == 0` and re-reads the sentinel row.
