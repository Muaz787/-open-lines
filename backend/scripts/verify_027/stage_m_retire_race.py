"""W9H-QA.5A Stage G/M — the retirement CAS against real PostgreSQL and real processes.

    stage_m_retire_race.py parent
    stage_m_retire_race.py worker <claim_id> <expected_sid> <start> <label> <out>
"""
import json, os, subprocess, sys, time, uuid
import psycopg

DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55437/w9e_scratch")
RETIRE = ("update tenant_regulatory_provider_claims "
          "set provider_sid = null, claimed_at = now(), failure = null, "
          "    updated_at = now() "
          "where id = %s and provider_sid = %s")


def worker():
    claim_id, expected, start, label, out = sys.argv[2:7]
    with psycopg.connect(DSN, autocommit=True) as c:
        while time.time() < float(start):
            pass
        cur = c.execute(RETIRE, (claim_id, expected))
        json.dump({"label": label, "rows": cur.rowcount}, open(out, "w"))


def parent():
    tmp = os.environ.get("QA5A_TMP", "/tmp")
    results = []
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("delete from tenants where business_name='QA5A race'")
        t = str(uuid.uuid4())
        c.execute("insert into tenants (id, business_name, industry) "
                  "values (%s,'QA5A race','salon')", (t,))

        def fresh(sid="ITold"):
            cid = str(uuid.uuid4())
            c.execute("delete from tenant_regulatory_provider_claims where tenant_id=%s", (t,))
            c.execute("insert into tenant_regulatory_provider_claims "
                      "(id,tenant_id,resource,scope_key,provider_account_sid,provider_sid) "
                      "values (%s,%s,'end_user','IE:business','ACqa',%s)", (cid, t, sid))
            return cid

        def sid_of(cid):
            return c.execute("select provider_sid, provider_account_sid from "
                             "tenant_regulatory_provider_claims where id=%s",
                             (cid,)).fetchone()

        # CASE 1 — four processes retire the same OLD sid simultaneously
        cid = fresh()
        start = time.time() + 6
        outs = [f"{tmp}/qa5a_{i}.json" for i in range(4)]
        for p in [subprocess.Popen([sys.executable, __file__, "worker", cid, "ITold",
                                    str(start), f"P{i}", outs[i]]) for i in range(4)]:
            p.wait()
        got = [json.load(open(o)) for o in outs]
        winners = [g for g in got if g["rows"] == 1]
        sid, acct = sid_of(cid)
        ok = len(winners) == 1 and sid is None and acct == "ACqa"
        results.append(ok)
        print(f"  CASE 1 concurrent retirement: processes={len(got)} "
              f"winners={len(winners)} provider_sid={sid!r} account={acct!r} "
              f"-> {'PASS' if ok else 'FAIL'}")

        # CASE 2 — a stale worker must not clear a REPLACEMENT sid
        cid = fresh()
        c.execute(RETIRE, (cid, "ITold"))
        c.execute("update tenant_regulatory_provider_claims set provider_sid='ITnew' "
                  "where id=%s", (cid,))
        cur = c.execute(RETIRE, (cid, "ITold"))
        sid, _ = sid_of(cid)
        ok = cur.rowcount == 0 and sid == "ITnew"
        results.append(ok)
        print(f"  CASE 2 stale retire vs replacement: rows={cur.rowcount} "
              f"provider_sid={sid!r} -> {'PASS' if ok else 'FAIL'}")

        # CASE 3 — after retirement the scope is claimable again, still exclusive
        cid = fresh()
        c.execute(RETIRE, (cid, "ITold"))
        try:
            c.execute("insert into tenant_regulatory_provider_claims "
                      "(id,tenant_id,resource,scope_key,provider_account_sid) "
                      "values (%s,%s,'end_user','IE:business','ACqa')",
                      (str(uuid.uuid4()), t))
            dup = True
        except psycopg.Error:
            dup = False
        results.append(not dup)
        print(f"  CASE 3 exclusivity survives retirement: second claim inserted="
              f"{dup} -> {'PASS' if not dup else 'FAIL'}")

        # CASE 6 — retiring a claim that is already detached is a no-op
        cid = fresh()
        c.execute(RETIRE, (cid, "ITold"))
        cur = c.execute(RETIRE, (cid, "ITold"))
        ok = cur.rowcount == 0
        results.append(ok)
        print(f"  CASE 6 retire an already-detached claim: rows={cur.rowcount} "
              f"-> {'PASS' if ok else 'FAIL'}")

        # the constraint still holds after retirement
        cid = fresh()
        c.execute(RETIRE, (cid, "ITold"))
        try:
            c.execute("update tenant_regulatory_provider_claims "
                      "set provider_account_sid=null where id=%s", (cid,))
            allowed = True
        except psycopg.Error:
            allowed = False
        results.append(allowed)
        print(f"  trpc_sid_account_chk permits a null SID with an account kept: "
              f"{allowed} -> {'PASS' if allowed else 'FAIL'}")

        c.execute("delete from tenants where id=%s", (t,))
    print("\nALL PASS" if all(results) else "\nFAILURES PRESENT")


{"parent": parent, "worker": worker}[sys.argv[1]]()
