"""W9E Stage C — pg_catalog verification of migration 027 on real PostgreSQL."""
import psycopg, json, os
DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55432/w9e_scratch")
NEW = ("tenant_regulatory_addresses", "tenant_regulatory_profiles",
       "tenant_phone_numbers", "tenant_regulatory_events")
ok = True
def ck(label, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))

with psycopg.connect(DSN, autocommit=True) as c:
    q = lambda s, *a: c.execute(s, a).fetchall()

    print("══ TABLES ══")
    rows = q("""select c.relname, c.relrowsecurity, c.relforcerowsecurity
                from pg_class c join pg_namespace n on n.oid=c.relnamespace
                where n.nspname='public' and c.relname = any(%s) order by 1""", list(NEW))
    ck("all four tables exist", len(rows) == 4, f"{[r[0] for r in rows]}")
    for name, rls, force in rows:
        print(f"        {name:32s} relrowsecurity={rls} relforcerowsecurity={force}")

    print("\n══ tenants.business_country_code ══")
    col = q("""select data_type, is_nullable, column_default from information_schema.columns
               where table_name='tenants' and column_name='business_country_code'""")
    ck("column exists", bool(col), str(col))
    ck("is text", col and col[0][0] == "text", str(col[0][0]) if col else "")
    ck("is nullable", col and col[0][1] == "YES")
    ck("has no default", col and col[0][2] is None)

    print("\n══ CHECK CONSTRAINTS ══")
    checks = q("""select conname, pg_get_constraintdef(oid) from pg_constraint
                  where contype='c' and conrelid::regclass::text = any(%s)
                     or (contype='c' and conname='tenants_business_country_code_chk')
                  order by conname""", list(NEW))
    for name, defn in checks:
        print(f"        {name:36s} {defn[:110]}")
    ck("expected CHECK count", len(checks) >= 18, f"{len(checks)} found")

    print("\n══ COMPOSITE FOREIGN KEYS ══")
    fks = q("""select conname, conrelid::regclass::text, pg_get_constraintdef(oid),
                      array_length(conkey,1), confdeltype
               from pg_constraint where contype='f'
                 and conrelid::regclass::text = any(%s) order by conname""", list(NEW))
    for name, tbl, defn, ncols, deltype in fks:
        print(f"        {name:28s} cols={ncols} ondel={deltype}  {defn[:82]}")
    composite = [f for f in fks if f[3] == 2]
    ck("six composite FKs on the new tables", len(composite) == 6,
       f"{len(composite)}: {[f[0] for f in composite]}")
    # 'c' = CASCADE. Changed from SET NULL after Stage E measured that SET NULL made
    # tenant deletion impossible (the tenant_id FK nulls tenant_id first, tripping
    # tre_profile_needs_tenant_chk).
    ck("event->profile FK is ON DELETE CASCADE",
       any(f[0] == "tre_profile_owner_fk" and f[4] == "c" for f in fks))
    ck("event->tenant FK is ON DELETE CASCADE",
       any(f[1] == "tenant_regulatory_events" and f[3] == 1 and f[4] == "c" for f in fks))
    ck("no owner FK on the event ledger uses SET NULL",
       not any(f[1] == "tenant_regulatory_events" and f[4] == "n" for f in fks))
    ck("no single-column FK to an owned table",
       not any(f[3] == 1 and ("tenant_locations" in f[2] or
               "tenant_regulatory_addresses(" in f[2] or
               "tenant_regulatory_profiles(" in f[2]) for f in fks))

    print("\n══ tenant_locations composite ownership key ══")
    u = q("""select conname, pg_get_constraintdef(oid) from pg_constraint
             where conname='tenant_locations_tenant_id_id_key'""")
    ck("tenant_locations_tenant_id_id_key exists", bool(u), str(u[0][1]) if u else "missing")

    print("\n══ PARTIAL INDEXES ══")
    idx = q("""select i.relname, pg_get_indexdef(i.oid), ix.indisunique
               from pg_index ix join pg_class i on i.oid=ix.indexrelid
               join pg_class t on t.oid=ix.indrelid
               join pg_namespace n on n.oid=t.relnamespace
               where n.nspname='public' and t.relname = any(%s) order by 1""", list(NEW))
    partial = [r for r in idx if " WHERE " in r[1]]
    for name, defn, uniq in idx:
        mark = "UNIQUE" if uniq else "      "
        print(f"        {mark} {name:36s} {defn.split(' ON ')[1][:95]}")
    ck("thirteen partial indexes", len(partial) == 13, f"{len(partial)} found")
    want = {"tpn_one_current_permanent", "tpn_one_live_temporary", "tpn_owned_e164_key",
            "tpn_provider_object_key", "trp_country_scope_key", "trp_address_scope_key",
            "trp_bundle_sid_key", "tra_location_scope_key", "tra_tenant_scope_key",
            "tra_address_sid_key", "tra_document_sid_key", "tre_fingerprint_occurrence_key"}
    have = {r[0] for r in idx if r[2]}
    ck("every named unique index present", want <= have, f"missing={want - have}")

    print("\n══ POLICIES ══")
    pol = q("""select policyname, tablename from pg_policies
               where schemaname='public' and tablename = any(%s)""", list(NEW))
    ck("no policies on the new tables", not pol, str(pol))
    allpol = q("select count(*) from pg_policies where schemaname='public'")
    print(f"        policies anywhere in public schema: {allpol[0][0]}")

    print("\n══ gen_random_uuid() ══")
    v = q("select gen_random_uuid()")
    ck("gen_random_uuid() works (built in since PG13, no pgcrypto needed)", bool(v[0][0]))
    ext = q("select extname from pg_extension order by 1")
    print(f"        extensions installed: {[e[0] for e in ext]}")

print(f"\n  STAGE C: {'ALL PASS' if ok else 'FAILURES'}")
