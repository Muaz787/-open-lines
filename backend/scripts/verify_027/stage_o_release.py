"""W9I-B.1 Stage K/L — the canonical release lifecycle against real PostgreSQL.

The Python suite proves the SERVICE decisions by patching the repository layer.
What it cannot prove is that PostgreSQL agrees: that a 'released' row really does
fall out of every partial unique index, that the fenced UPDATE really does match
zero rows when the identity has moved, and that four concurrent releases really
do produce one winner. Those are properties of the database, and only the
database can answer for them.

Nothing here needs a migration. 027 already declares `released`, `released_at`
and index predicates that exclude it -- the application simply never performed
the transition. These proofs are what establish that claim rather than assert it.

Run as:
    stage_o_release.py parent
    stage_o_release.py worker <row_id> <start_ts> <label> <out>
"""
import json, os, subprocess, sys, time, uuid
import psycopg

DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55433/w9e_scratch")
TMP = os.environ.get("W9IB1_TMP", "/tmp")

E1 = "+14165550100"
SID1 = "PN_qa_one"
ACCT = "ACqa_sub"

# The fenced release, verbatim in shape from db/phone_numbers.release_number_cas:
# every identity column in the WHERE clause, and only releasable statuses.
RELEASE = """
update tenant_phone_numbers
   set status = 'released', released_at = now(), updated_at = now()
 where id = %s and tenant_id = %s and e164 = %s
   and provider_account_sid = %s and provider_sid = %s
   and status in ('provisioning','active','retiring')
"""


def worker():
    row_id, start, label, out = sys.argv[2:6]
    tenant_id = os.environ["W9IB1_TENANT"]
    with psycopg.connect(DSN, autocommit=True) as c:
        while time.time() < float(start):
            pass
        cur = c.execute(RELEASE, (row_id, tenant_id, E1 + "0", ACCT, SID1 + "_race"))
        res = {"label": label, "rows": cur.rowcount}
        json.dump(res, open(out, "w"))
        print(f"[{label}] {json.dumps(res)}")


def parent():
    ok = []
    def chk(l, cond, d=""):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {l}{'  ' + str(d) if d else ''}")

    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("delete from tenants where business_name like 'W9IB1%'")
        tid = str(uuid.uuid4())
        c.execute("insert into tenants (id, business_name, industry) "
                  "values (%s,'W9IB1 release','realtor')", (tid,))

        def add(e164, sid, status, purpose="permanent", rid=None):
            rid = rid or str(uuid.uuid4())
            c.execute(
                "insert into tenant_phone_numbers (id, tenant_id, e164, purpose, status,"
                " provider, provider_account_sid, provider_sid, iso_country)"
                " values (%s,%s,%s,%s,%s,'twilio',%s,%s,'CA')",
                (rid, tid, e164, purpose, status, ACCT, sid))
            return rid

        # ── 1. the transition the application was missing ────────────────────
        row1 = add(E1, SID1, "active")
        cur = c.execute(RELEASE, (row1, tid, E1, ACCT, SID1))
        chk("O1 a live permanent row transitions to released", cur.rowcount == 1, cur.rowcount)
        st = c.execute("select status, released_at from tenant_phone_numbers where id=%s",
                       (row1,)).fetchone()
        chk("O2 the row reads released and is stamped", st[0] == "released" and st[1] is not None, st[0])

        # ── 2. released falls out of every index predicate ───────────────────
        n = c.execute("select count(*) from tenant_phone_numbers where e164=%s "
                      "and status in ('active','retiring')", (E1,)).fetchone()[0]
        chk("O3 released is not routable (ROUTABLE_STATUSES)", n == 0, n)

        # A replacement permanent may now be registered for the SAME tenant.
        try:
            row2 = add("+14165559999", "PN_qa_two", "provisioning")
            chk("O4 a replacement permanent is permitted alongside a released one", True)
        except psycopg.Error as e:
            chk("O4 a replacement permanent is permitted alongside a released one",
                False, f"{e.sqlstate} {getattr(e.diag,'constraint_name',None)}")
            row2 = None

        # And the released E.164 is re-purchasable -- by a DIFFERENT tenant.
        tid2 = str(uuid.uuid4())
        c.execute("insert into tenants (id, business_name, industry) "
                  "values (%s,'W9IB1 other','realtor')", (tid2,))
        try:
            c.execute(
                "insert into tenant_phone_numbers (id, tenant_id, e164, purpose, status,"
                " provider, provider_account_sid, provider_sid, iso_country)"
                " values (%s,%s,%s,'permanent','provisioning','twilio',%s,'PN_qa_three','CA')",
                (str(uuid.uuid4()), tid2, E1, "ACother"))
            chk("O5 the released E.164 is re-purchasable by another tenant", True)
        except psycopg.Error as e:
            chk("O5 the released E.164 is re-purchasable by another tenant",
                False, f"{e.sqlstate} {getattr(e.diag,'constraint_name',None)}")

        # ── 3. what the release must NOT permit ──────────────────────────────
        # The provider object stays unique even though the row is history: Twilio
        # never reissues a SID, so a second row claiming it is a real error.
        try:
            c.execute(
                "insert into tenant_phone_numbers (id, tenant_id, e164, purpose, status,"
                " provider, provider_account_sid, provider_sid, iso_country)"
                " values (%s,%s,'+14165550101','permanent','failed','twilio',%s,%s,'CA')",
                (str(uuid.uuid4()), tid, ACCT, SID1))
            chk("O6 a released row still owns its provider SID", False, "insert succeeded")
        except psycopg.Error as e:
            chk("O6 a released row still owns its provider SID",
                e.sqlstate == "23505" and getattr(e.diag, "constraint_name", None)
                == "tpn_provider_object_key",
                getattr(e.diag, "constraint_name", None))

        # Re-running the release matches zero rows rather than restamping.
        first_stamp = c.execute("select released_at from tenant_phone_numbers where id=%s",
                                (row1,)).fetchone()[0]
        cur = c.execute(RELEASE, (row1, tid, E1, ACCT, SID1))
        chk("O7 re-releasing an already-released row changes nothing", cur.rowcount == 0, cur.rowcount)
        again = c.execute("select released_at from tenant_phone_numbers where id=%s",
                          (row1,)).fetchone()[0]
        chk("O8 the original released_at survives the retry", again == first_stamp)

        # The fence: a worker holding a stale identity must match nothing.
        if row2:
            for label, args in (
                ("a stale E.164", (row2, tid, E1, ACCT, "PN_qa_two")),
                ("a stale provider SID", (row2, tid, "+14165559999", ACCT, SID1)),
                ("a stale account SID", (row2, tid, "+14165559999", "ACstale", "PN_qa_two")),
                ("another tenant's id", (row2, tid2, "+14165559999", ACCT, "PN_qa_two")),
            ):
                cur = c.execute(RELEASE, args)
                chk(f"O9 the fence refuses {label}", cur.rowcount == 0, cur.rowcount)
            st = c.execute("select status from tenant_phone_numbers where id=%s",
                           (row2,)).fetchone()[0]
            chk("O10 the replacement is untouched by every stale attempt",
                st == "provisioning", st)

        # A released row cannot be released again into 'active' by this statement,
        # and a 'failed' row is equally terminal.
        rowf = add("+14165550102", "PN_qa_four", "failed")
        cur = c.execute(RELEASE, (rowf, tid, "+14165550102", ACCT, "PN_qa_four"))
        chk("O11 a failed row is terminal too — the release matches nothing",
            cur.rowcount == 0, cur.rowcount)

        # ── 4. real OS-level concurrency ─────────────────────────────────────
        # A FRESH tenant for the race. Resurrecting row1 to 'active' alongside
        # the replacement is not possible -- tpn_one_current_permanent refuses a
        # second live permanent, which is the index doing exactly its job.
        tid = str(uuid.uuid4())
        c.execute("insert into tenants (id, business_name, industry) "
                  "values (%s,'W9IB1 race','realtor')", (tid,))
        row1 = str(uuid.uuid4())
        c.execute(
            "insert into tenant_phone_numbers (id, tenant_id, e164, purpose, status,"
            " provider, provider_account_sid, provider_sid, iso_country)"
            " values (%s,%s,%s,'permanent','active','twilio',%s,%s,'CA')",
            (row1, tid, E1 + "0", ACCT, SID1 + "_race"))
        os.environ["W9IB1_TENANT"] = tid

    start = time.time() + 2.0
    outs, procs = [], []
    for i in range(4):
        out = f"{TMP}/w9ib1_race_{i}.json"
        outs.append(out)
        procs.append(subprocess.Popen(
            [sys.executable, __file__, "worker", row1, str(start), f"w{i}", out],
            env={**os.environ, "W9IB1_TENANT": tid}))
    for p in procs:
        p.wait()
    res = [json.load(open(o)) for o in outs]
    winners = [r for r in res if r["rows"] == 1]
    chk("O12 four concurrent releases produce exactly one winner",
        len(winners) == 1, [r["rows"] for r in res])
    chk("O13 every loser changed zero rows",
        all(r["rows"] == 0 for r in res if r not in winners))

    with psycopg.connect(DSN, autocommit=True) as c:
        st = c.execute("select status, released_at from tenant_phone_numbers where id=%s",
                       (row1,)).fetchone()
        chk("O14 the row is released exactly once", st[0] == "released" and st[1] is not None, st[0])
        n = c.execute("select count(*) from tenant_phone_numbers where tenant_id=%s "
                      "and purpose='permanent' and status in ('provisioning','active')",
                      (tid,)).fetchone()[0]
        chk("O15 no live permanent remains after the raced release", n == 0, n)
        c.execute("delete from tenants where business_name like 'W9IB1%'")

    print(f"\n  STAGE O: {sum(ok)}/{len(ok)} passed" +
          ("  ALL PASS" if all(ok) else "  FAILURES"))
    return all(ok)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker()
    else:
        sys.exit(0 if parent() else 1)
