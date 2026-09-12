"""W9I-B — real proofs of migration 031's invariants and its backfill."""
import os, uuid
import psycopg
DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55440/w9ib_prod")
results = []
def ok(n,l,q,a=(),*,conn):
    try:
        with conn.transaction(): conn.execute(q,a)
        results.append((n,"PASS",l,"accepted"))
    except Exception as e:
        results.append((n,"FAIL",l,f"unexpectedly REJECTED: {e}"))
def reject(n,l,q,a=(),state=None,con=None,*,conn):
    try:
        with conn.transaction(): conn.execute(q,a)
        results.append((n,"FAIL",l,"was ACCEPTED — constraint absent"))
    except psycopg.Error as e:
        c=getattr(getattr(e,"diag",None),"constraint_name",None) or ""
        good=(state is None or e.sqlstate==state) and (con is None or con in c)
        results.append((n,"PASS" if good else "FAIL",l,f"{e.sqlstate} {c or str(e).splitlines()[0][:50]}"))

T="insert into tenants (id, business_name, industry, onboarding_state, onboarding_key) values (%s,%s,'salon',%s,%s)"
with psycopg.connect(DSN, autocommit=True) as c:
    c.execute("delete from tenants where business_name like 'W9IB %'")
    for n,st in enumerate(("provisioning","regulatory_required","active"), start=1):
        ok(n, f"onboarding_state '{st}' accepted", T,
           (str(uuid.uuid4()), f"W9IB {st}", st, None), conn=c)
    ok(4, "NULL onboarding_state accepted (pre-lifecycle rows)", T,
       (str(uuid.uuid4()), "W9IB null", None, None), conn=c)
    reject(5, "an invented state is refused", T,
           (str(uuid.uuid4()), "W9IB bad", "half_done", None),
           "23514", "tenants_onboarding_state_chk", conn=c)
    reject(6, "'complete' is refused (not in the vocabulary)", T,
           (str(uuid.uuid4()), "W9IB bad2", "complete", None),
           "23514", "tenants_onboarding_state_chk", conn=c)

    K = str(uuid.uuid4())
    ok(7, "an onboarding key is accepted", T,
       (str(uuid.uuid4()), "W9IB key a", "provisioning", K), conn=c)
    reject(8, "the SAME key cannot create a second tenant", T,
           (str(uuid.uuid4()), "W9IB key b", "provisioning", K),
           "23505", "tenants_onboarding_key_uq", conn=c)
    ok(9, "a different key is fine", T,
       (str(uuid.uuid4()), "W9IB key c", "provisioning", str(uuid.uuid4())), conn=c)
    ok(10, "MANY tenants may have NO key (partial index)", T,
       (str(uuid.uuid4()), "W9IB nokey 1", "active", None), conn=c)
    ok(11, "...and another", T,
       (str(uuid.uuid4()), "W9IB nokey 2", "active", None), conn=c)

    # the backfill, on rows that look like today's production
    c.execute("delete from tenants where business_name like 'W9IB %'")
    WITH, WITHOUT = str(uuid.uuid4()), str(uuid.uuid4())
    c.execute("insert into tenants (id, business_name, industry, twilio_phone_number) "
              "values (%s,'W9IB backfill with','salon','+14165550123')", (WITH,))
    c.execute("insert into tenants (id, business_name, industry) "
              "values (%s,'W9IB backfill without','salon')", (WITHOUT,))
    c.execute("update tenants set onboarding_state = null where id in (%s,%s)", (WITH, WITHOUT))
    with open("../../../migrations/031_onboarding_lifecycle.sql") as f:
        c.execute(f.read())
    a = c.execute("select onboarding_state from tenants where id=%s",(WITH,)).fetchone()[0]
    b = c.execute("select onboarding_state from tenants where id=%s",(WITHOUT,)).fetchone()[0]
    results.append((12,"PASS" if a=="active" else "FAIL",
                    "backfill: a tenant WITH a number becomes 'active'", str(a)))
    results.append((13,"PASS" if b=="provisioning" else "FAIL",
                    "backfill: a tenant WITHOUT one becomes 'provisioning'", str(b)))
    # and a re-run must not overwrite a state the app has since set
    c.execute("update tenants set onboarding_state='regulatory_required' where id=%s",(WITHOUT,))
    with open("../../../migrations/031_onboarding_lifecycle.sql") as f:
        c.execute(f.read())
    d = c.execute("select onboarding_state from tenants where id=%s",(WITHOUT,)).fetchone()[0]
    results.append((14,"PASS" if d=="regulatory_required" else "FAIL",
                    "a re-run does NOT overwrite an application-set state", str(d)))
    n = c.execute("select count(*) from tenants where onboarding_state is null").fetchone()[0]
    results.append((15,"PASS" if n==0 else "FAIL",
                    "no tenant is left without a state after the backfill", f"null={n}"))
    nreg = c.execute("select count(*) from tenants where onboarding_state='regulatory_required' "
                     "and id <> %s",(WITHOUT,)).fetchone()[0]
    results.append((16,"PASS" if nreg==0 else "FAIL",
                    "the backfill invents NO regulatory obligation", f"count={nreg}"))
    c.execute("delete from tenants where business_name like 'W9IB %'")

bad=[r for r in results if r[1]!="PASS"]
for n,s,l,d in sorted(results): print(f"  [{s}] {n:>2}. {l}\n        {d}")
print(f"\n{len(results)-len(bad)}/{len(results)} passed")
print("ALL PASS" if not bad else "FAILURES PRESENT")
