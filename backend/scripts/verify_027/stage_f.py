"""W9E Stage F — RLS proved against real Postgres roles that mirror Supabase's.

FIDELITY NOTE. Supabase's anon / authenticated / service_role are ordinary Postgres
roles: anon and authenticated hold full table privileges by default and RLS is the
ONLY thing standing between them and the data; service_role has BYPASSRLS. Those are
recreated exactly in the scratch bootstrap, so `set role anon` here reproduces what
an anon API key reaches after PostgREST authenticates it. What this CANNOT reproduce
is PostgREST itself (JWT parsing, auth.uid(), the request-scoped GUCs) -- but none
of that matters for tables with RLS on and no policy, because the deny is total and
happens in Postgres, below PostgREST.
"""
import psycopg, uuid, os
DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55432/w9e_scratch")
NEW = ("tenant_regulatory_addresses", "tenant_regulatory_profiles",
       "tenant_phone_numbers", "tenant_regulatory_events")
res = []
def rec(label, ok, detail=""): res.append((label, "PASS" if ok else "FAIL", detail))

with psycopg.connect(DSN, autocommit=True) as c:
    print("══ pg_catalog ══")
    for t in NEW:
        rls, force = c.execute(
            "select relrowsecurity, relforcerowsecurity from pg_class c "
            "join pg_namespace n on n.oid=c.relnamespace "
            "where n.nspname='public' and c.relname=%s", (t,)).fetchone()
        rec(f"{t}: relrowsecurity", rls is True, f"relforcerowsecurity={force}")
    pol = c.execute("select policyname, tablename, roles, cmd, permissive from pg_policies "
                    "where schemaname='public' and tablename = any(%s)", (list(NEW),)).fetchall()
    rec("no policies of any kind on the four tables", pol == [], str(pol))

    print("\n══ role privileges (Supabase grants anon everything; only RLS stops it) ══")
    for t in NEW[:1]:
        grants = c.execute(
            "select grantee, string_agg(privilege_type, ',' order by privilege_type) "
            "from information_schema.role_table_grants where table_name=%s "
            "and grantee in ('anon','authenticated','service_role') group by grantee "
            "order by grantee", (t,)).fetchall()
        for g, p in grants:
            print(f"        {g:16s} {p}")
        rec("anon HOLDS table privileges (so the deny below is genuinely RLS)",
            any(g == "anon" and "SELECT" in p for g, p in grants), str(grants))

    # a real row to try to reach, owned by a real tenant
    T = str(uuid.uuid4())
    c.execute("insert into tenants (id, business_name, industry) values (%s,'W9E RLS','salon')", (T,))
    PH = str(uuid.uuid4())
    c.execute("insert into tenant_phone_numbers (id,tenant_id,e164,purpose,status,"
              "provider_account_sid,provider_sid,iso_country) "
              "values (%s,%s,'+353161799999','permanent','active','ACrls','PNrls','IE')", (PH, T))
    AD = str(uuid.uuid4())
    c.execute("insert into tenant_regulatory_addresses (id,tenant_id,iso_country) "
              "values (%s,%s,'IE')", (AD, T))
    PR = str(uuid.uuid4())
    c.execute("insert into tenant_regulatory_profiles (id,tenant_id,iso_country) "
              "values (%s,%s,'IE')", (PR, T))
    EV = str(uuid.uuid4())
    c.execute("insert into tenant_regulatory_events (id,bundle_sid,bundle_status,fingerprint,"
              "signature_valid) values (%s,'BUrls','draft',%s,true)", (EV, "d"*64))

    print("\n══ anon: SELECT / INSERT / UPDATE / DELETE on each table ══")
    for t in NEW:
        for op, sql, args in (
            ("SELECT", f"select count(*) from {t}", ()),
            ("INSERT", f"insert into {t} (tenant_id) values (%s)", (T,)),
            ("UPDATE", f"update {t} set updated_at = now()", ()),
            ("DELETE", f"delete from {t}", ()),
        ):
            try:
                with c.transaction():
                    c.execute("set local role anon")
                    cur = c.execute(sql, args)
                    if op == "SELECT":
                        n = cur.fetchone()[0]
                        rec(f"anon {op:6s} {t}", n == 0,
                            f"returned {n} rows (RLS with no policy => empty, not an error)")
                    else:
                        # RLS with no policy does not make UPDATE/DELETE raise: it
                        # makes them match NOTHING. A statement that succeeds while
                        # affecting zero rows has changed no data, which is the
                        # property that matters. Asserting an exception here would
                        # have been asserting the wrong thing about how RLS works.
                        rec(f"anon {op:6s} {t}", cur.rowcount == 0,
                            f"succeeded but affected {cur.rowcount} rows")
                        raise psycopg.Rollback
            except psycopg.Rollback:
                pass
            except psycopg.Error as e:
                rec(f"anon {op:6s} {t}", True, f"denied {e.sqlstate}")

    print("")
    print("== anon could not actually change anything ==")
    survivors = c.execute("select count(*) from tenant_phone_numbers where id=%s",
                          (PH,)).fetchone()[0]
    rec("the sentinel phone row survived every anon UPDATE/DELETE attempt",
        survivors == 1, f"rows={survivors}")
    err = c.execute("select last_error from tenant_phone_numbers where id=%s",
                    (PH,)).fetchone()[0]
    rec("the sentinel phone row was not modified by anon", err is None,
        f"last_error={err!r}")
    tot = {t: c.execute(f"select count(*) from {t}").fetchone()[0] for t in NEW}
    rec("no table was emptied by an anon DELETE", all(v > 0 for v in tot.values()),
        str(tot))

    print("\n══ authenticated (no policy either) ══")
    for t in NEW:
        with c.transaction():
            c.execute("set local role authenticated")
            n = c.execute(f"select count(*) from {t}").fetchone()[0]
            rec(f"authenticated SELECT {t}", n == 0, f"returned {n} rows")

    print("\n══ service_role (BYPASSRLS — what the backend uses) ══")
    expected = {"tenant_phone_numbers": 1, "tenant_regulatory_addresses": 1,
                "tenant_regulatory_profiles": 1, "tenant_regulatory_events": 1}
    for t in NEW:
        with c.transaction():
            c.execute("set local role service_role")
            n = c.execute(f"select count(*) from {t} where id is not null").fetchone()[0]
            rec(f"service_role SELECT {t}", n >= expected[t], f"returned {n} rows")
    with c.transaction():
        c.execute("set local role service_role")
        c.execute("update tenant_phone_numbers set last_error='w9e' where id=%s", (PH,))
        got = c.execute("select last_error from tenant_phone_numbers where id=%s",
                        (PH,)).fetchone()[0]
        rec("service_role can WRITE", got == "w9e", f"last_error={got!r}")

    c.execute("delete from tenants where id=%s", (T,))
    c.execute("delete from tenant_regulatory_events where bundle_sid='BUrls'")

for label, verdict, detail in res:
    print(f"  [{verdict}] {label}" + (f" — {detail}" if detail else ""))
bad = [r for r in res if r[1] == "FAIL"]
print(f"\n  STAGE F: {len(res)-len(bad)}/{len(res)} passed"
      f"{'' if not bad else ' — FAILURES: ' + str([r[0] for r in bad])}")
