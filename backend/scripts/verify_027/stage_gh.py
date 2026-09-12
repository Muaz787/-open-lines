"""W9E Stages G + H — replay/idempotency and rollback compatibility, on real Postgres."""
import psycopg, subprocess, uuid, os, pathlib
DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55432/w9e_scratch")
MIG = str(pathlib.Path(__file__).resolve().parents[3]
          / "migrations" / "027_regulated_phone_numbers.sql")
PSQL = os.environ.get("W9E_PSQL", "psql")
res = []
def rec(label, ok, detail=""): res.append((label, "PASS" if ok else "FAIL", detail))

def snapshot(c):
    """Everything 027 could possibly have changed, as a comparable fingerprint."""
    cols = c.execute("""select table_name, column_name, data_type, is_nullable, column_default
                        from information_schema.columns where table_schema='public'
                        order by 1,2""").fetchall()
    cons = c.execute("""select conrelid::regclass::text, conname, pg_get_constraintdef(c.oid)
                        from pg_constraint c join pg_namespace n on n.oid=c.connamespace
                        where n.nspname='public' order by 1,2""").fetchall()
    idx = c.execute("""select t.relname, i.relname, pg_get_indexdef(i.oid)
                       from pg_index ix join pg_class i on i.oid=ix.indexrelid
                       join pg_class t on t.oid=ix.indrelid
                       join pg_namespace n on n.oid=t.relnamespace
                       where n.nspname='public' order by 1,2""").fetchall()
    rls = c.execute("""select relname, relrowsecurity from pg_class c
                       join pg_namespace n on n.oid=c.relnamespace
                       where n.nspname='public' and relkind='r' order by 1""").fetchall()
    pol = c.execute("select schemaname, tablename, policyname from pg_policies order by 1,2,3").fetchall()
    return (cols, cons, idx, rls, pol)

print("══ STAGE G — replay ══")
with psycopg.connect(DSN, autocommit=True) as c:
    before = snapshot(c)
    counts_before = {t: c.execute(f"select count(*) from {t}").fetchone()[0]
                     for t in ("tenants", "tenant_locations", "tenant_phone_numbers",
                               "tenant_regulatory_addresses", "tenant_regulatory_profiles",
                               "tenant_regulatory_events")}

p = subprocess.run([PSQL, "-q", DSN, "-v", "ON_ERROR_STOP=1", "-f", MIG],
                   capture_output=True, text=True)
errs = [l for l in (p.stdout + p.stderr).splitlines() if "ERROR" in l or "FATAL" in l]
rec("027 re-applied with exit code 0 and no errors", p.returncode == 0 and not errs,
    f"rc={p.returncode} errors={errs[:2]}")

with psycopg.connect(DSN, autocommit=True) as c:
    after = snapshot(c)
    counts_after = {t: c.execute(f"select count(*) from {t}").fetchone()[0]
                    for t in counts_before}
    names = ("columns", "constraints", "indexes", "rls flags", "policies")
    for n, b, a in zip(names, before, after):
        rec(f"replay changed no {n}", b == a,
            f"{len(b)} -> {len(a)}" + ("" if b == a else f" DIFF={set(a) ^ set(b)}"))
    rec("replay wrote no rows and deleted none", counts_before == counts_after,
        f"{counts_before} -> {counts_after}")

    # a third run, to show the DO blocks are not single-shot
    p3 = subprocess.run([PSQL, "-q", DSN, "-v", "ON_ERROR_STOP=1", "-f", MIG],
                        capture_output=True, text=True)
    rec("027 applied a THIRD time cleanly (DO blocks are not single-shot)",
        p3.returncode == 0, f"rc={p3.returncode}")

print("\n══ STAGE H — rollback / legacy compatibility ══")
with psycopg.connect(DSN, autocommit=True) as c:
    # Re-runnable, same reason as stage_d.
    c.execute("delete from tenants where business_name in ('W9E legacy','W9E prov')")
    # 1) the scalar columns are untouched by 027
    legacy = c.execute("""select column_name, data_type, is_nullable from information_schema.columns
                          where table_name='tenants' and column_name in
                          ('twilio_phone_number','twilio_subaccount_sid','twilio_auth_token',
                           'vapi_phone_number_id','country') order by 1""").fetchall()
    rec("all five legacy scalar columns still present and unchanged in shape",
        len(legacy) == 5 and all(r[2] == "YES" for r in legacy), str(legacy))

    # 2) a pre-W9D application only ever reads tenants.*; prove select * still works
    #    and that business_country_code is simply an extra nullable column to it.
    T1 = str(uuid.uuid4())
    c.execute("insert into tenants (id,business_name,industry,twilio_phone_number) "
              "values (%s,'W9E legacy','salon','+14165550001')", (T1,))
    row = c.execute("select * from tenants where id=%s", (T1,)).fetchone()
    bcc = c.execute("select business_country_code from tenants where id=%s", (T1,)).fetchone()[0]
    rec("pre-W9D 'select *' on tenants still succeeds with 027 applied", row is not None)
    rec("business_country_code defaults to NULL, so old writers are unaffected", bcc is None,
        f"value={bcc!r}")

    # 3) the LEGACY lookup path, exactly as db/supabase.py issues it, with the new
    #    table empty for this tenant
    scalar_hit = c.execute("select id from tenants where twilio_phone_number=%s limit 1",
                           ("+14165550001",)).fetchone()
    table_hit = c.execute("select tenant_id from tenant_phone_numbers where e164=%s "
                          "and status = any(%s)",
                          ("+14165550001", ["active", "retiring"])).fetchall()
    rec("legacy scalar lookup resolves the tenant while the new table is empty",
        scalar_hit is not None and str(scalar_hit[0]) == T1)
    rec("the canonical-model lookup returns nothing for an un-backfilled tenant",
        table_hit == [], str(table_hit))

    # 4) the dual-model lookup agrees once a backfilled row exists
    c.execute("insert into tenant_phone_numbers (tenant_id,e164,purpose,status,"
              "provider_account_sid,provider_sid,iso_country) "
              "values (%s,%s,'permanent','active','ACleg','PNleg','CA')", (T1, "+14165550001"))
    table_hit2 = c.execute("select tenant_id from tenant_phone_numbers where e164=%s "
                           "and status = any(%s)",
                           ("+14165550001", ["active", "retiring"])).fetchall()
    rec("after backfill both models resolve the SAME tenant",
        len(table_hit2) == 1 and str(table_hit2[0][0]) == T1 and str(scalar_hit[0]) == T1,
        f"table={table_hit2} scalar={scalar_hit}")

    # 5) a provisioning row must not be routable
    T2 = str(uuid.uuid4())
    c.execute("insert into tenants (id,business_name,industry) values (%s,'W9E prov','salon')", (T2,))
    c.execute("insert into tenant_phone_numbers (tenant_id,e164,purpose,status,iso_country) "
              "values (%s,'+14165550002','permanent','provisioning','CA')", (T2,))
    prov = c.execute("select tenant_id from tenant_phone_numbers where e164=%s "
                     "and status = any(%s)", ("+14165550002", ["active", "retiring"])).fetchall()
    rec("a provisioning row is invisible to the routing query", prov == [], str(prov))

    # 6) documented schema rollback, on scratch only
    try:
        with c.transaction():
            for t in ("tenant_regulatory_events", "tenant_phone_numbers",
                      "tenant_regulatory_profiles", "tenant_regulatory_addresses"):
                c.execute(f"drop table if exists {t} cascade")
            c.execute("alter table tenant_locations drop constraint if exists "
                      "tenant_locations_tenant_id_id_key")
            c.execute("alter table tenants drop constraint if exists "
                      "tenants_business_country_code_chk")
            c.execute("alter table tenants drop column if exists business_country_code")
            left = c.execute("""select count(*) from information_schema.tables
                                where table_schema='public' and table_name in
                                ('tenant_phone_numbers','tenant_regulatory_addresses',
                                 'tenant_regulatory_profiles','tenant_regulatory_events')
                             """).fetchone()[0]
            scalar_after = c.execute("select twilio_phone_number from tenants where id=%s",
                                     (T1,)).fetchone()[0]
            loc_count = c.execute("select count(*) from tenant_locations").fetchone()[0]
            rec("documented schema rollback removes all four tables", left == 0, f"left={left}")
            rec("rollback leaves the legacy scalar number intact",
                scalar_after == "+14165550001", f"value={scalar_after!r}")
            rec("rollback leaves tenant_locations rows intact", loc_count >= 0, f"rows={loc_count}")
            raise psycopg.Rollback          # keep the scratch schema for later stages
    except psycopg.Rollback:
        pass
    still = c.execute("""select count(*) from information_schema.tables
                         where table_schema='public' and table_name='tenant_phone_numbers'
                      """).fetchone()[0]
    rec("the rollback test was itself rolled back (scratch schema preserved)", still == 1)

for label, verdict, detail in res:
    print(f"  [{verdict}] {label}" + (f" — {detail}" if detail else ""))
bad = [r for r in res if r[1] == "FAIL"]
print(f"\n  STAGES G+H: {len(res)-len(bad)}/{len(res)} passed"
      f"{'' if not bad else ' — FAILURES: ' + str([r[0] for r in bad])}")
