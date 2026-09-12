"""W9H-QA.4 Stage M — is the CLAIM exclusive under true OS-level concurrency?

The hardened engine cannot be raced end-to-end until migration 030 exists in the
database the application talks to, and 030 must not be applied to production in
this gate. What CAN be settled now is the question the whole design rests on:
when two independent processes race the same claim, does exactly one win?

Real PostgreSQL, real processes, wall-clock barrier. Run as:
    stage_l_race.py parent    (orchestrates)
    stage_l_race.py worker <resource> <scope> <start_ts> <label> <out>
"""
import json, os, subprocess, sys, time, uuid
import psycopg

DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55435/w9e_scratch")
CLAIM = ("insert into tenant_regulatory_provider_claims "
         "(id, tenant_id, resource, scope_key, provider_account_sid) "
         "values (%s,%s,%s,%s,'ACqa')")


def worker():
    resource, scope, start, label, out = sys.argv[2:7]
    tenant_id = os.environ["QA4_TENANT"]
    with psycopg.connect(DSN, autocommit=True) as c:
        while time.time() < float(start):
            pass
        res = {"label": label, "won": None, "sqlstate": None}
        try:
            c.execute(CLAIM, (str(uuid.uuid4()), tenant_id, resource, scope))
            res["won"] = True
        except psycopg.Error as e:
            # The loser must see a UNIQUE VIOLATION, which is exactly what the
            # data layer converts into "someone else owns it" rather than an error.
            res["won"] = False
            res["sqlstate"] = e.sqlstate
            res["constraint"] = getattr(getattr(e, "diag", None),
                                        "constraint_name", None)
        json.dump(res, open(out, "w"))
        print(f"[{label}] {json.dumps(res)}")


def parent():
    tmp = os.environ.get("QA4_TMP", "/tmp")
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("delete from tenants where business_name='QA4 race'")
        t = str(uuid.uuid4())
        c.execute("insert into tenants (id, business_name, industry) "
                  "values (%s,'QA4 race','salon')", (t,))
    env = {**os.environ, "QA4_TENANT": t}
    results = []
    for resource, scope in (("end_user", "IE:business"),
                            ("supporting_document", "addr-x:business_address"),
                            ("bundle", "prof-x")):
        start = time.time() + 6
        outs = [f"{tmp}/qa4_claim_{resource}_{i}.json" for i in range(4)]
        procs = [subprocess.Popen(
            [sys.executable, __file__, "worker", resource, scope, str(start),
             f"P{i}", outs[i]], env=env) for i in range(4)]
        for p in procs:
            p.wait()
        got = [json.load(open(o)) for o in outs if os.path.exists(o)]
        winners = [g for g in got if g["won"]]
        losers = [g for g in got if not g["won"]]
        with psycopg.connect(DSN, autocommit=True) as c:
            rows = c.execute("select count(*) from tenant_regulatory_provider_claims "
                             "where tenant_id=%s and resource=%s", (t, resource)).fetchone()[0]
        clean = (len(winners) == 1 and rows == 1
                 and all(l["sqlstate"] == "23505" for l in losers)
                 and all(l.get("constraint") == "trpc_scope_key" for l in losers))
        results.append(clean)
        print(f"  {resource:20s} processes={len(got)} winners={len(winners)} "
              f"losers={len(losers)} rows={rows} "
              f"loser_sqlstates={sorted({l['sqlstate'] for l in losers})} "
              f"-> {'PASS' if clean else 'FAIL'}")
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("delete from tenants where id=%s", (t,))
    print("\nALL PASS" if all(results) else "\nFAILURES PRESENT")


{"parent": parent, "worker": worker}[sys.argv[1]]()
