"""W9I-H.AUTO.1 — migration 036 against real PostgreSQL, BEFORE it is proposed.

The properties it exists for:
  * the free allowance and every lifecycle clock survive the NUMBER changing --
    that is why they live here and not on the phone row;
  * a temporary number cannot be recorded without a recorded provider attempt,
    so an ambiguous purchase can never look like a fresh one.

Run as:
    stage_x_temporary_access.py parent
    stage_x_temporary_access.py worker <tenant> <start> <label> <out>
"""
import hashlib, json, os, subprocess, sys, time, uuid
import psycopg

DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55433/w9e_scratch")
TMP = os.environ.get("W9IH2_TMP", "/tmp")
M036 = "/Users/muazmuhamed/open-lines/migrations/036_ireland_temporary_access.sql"

CLAIM = """
insert into ireland_temporary_access (tenant_id) values (%s)
on conflict (tenant_id) do nothing
"""
#: Written immediately BEFORE Twilio is asked to buy. Only its winner may spend.
MARK = """
update ireland_temporary_access
   set provider_attempt_at = now(), updated_at = now()
 where tenant_id = %s and provider_attempt_at is null
"""
ATTACH = """
update ireland_temporary_access
   set e164 = %s, provider_sid = %s, updated_at = now()
 where tenant_id = %s and e164 is null and provider_attempt_at is not null
"""
#: The ONLY route back toward a purchase, gated on proof rather than on age.
RETAKE = """
update ireland_temporary_access
   set updated_at = now()
 where tenant_id = %s and provider_attempt_at is null and e164 is null
"""
CONSUME = "select * from ita_consume_seconds(%s, %s)"


def _tenant(c, tid):
    """Insert into whatever `tenants` the replayed lineage actually created.

    NOT a table of our own: the FK must be exercised against the real one, and
    a create-if-not-exists would silently do nothing and prove nothing.
    """
    c.execute("insert into tenants (id, business_name, industry,"
              " business_country_code) values (%s,'W9IH AUTO fixture','realtor','IE')",
              (tid,))


def worker():
    tid, start, label, out = sys.argv[2:6]
    num = f"+1416555{uuid.uuid4().int % 10000:04d}"
    sid = f"PN{label}{uuid.uuid4().hex[:12]}"
    with psycopg.connect(DSN, autocommit=True) as c:
        while time.time() < float(start):
            pass
        c.execute(CLAIM, (tid,))
        may_buy = c.execute(MARK, (tid,)).rowcount == 1
        attached = c.execute(ATTACH, (num, sid, tid)).rowcount if may_buy else 0
        got = c.execute("select e164 from ireland_temporary_access where tenant_id=%s",
                        (tid,)).fetchone()[0]
        json.dump({"label": label, "may_buy": may_buy, "attached": attached, "saw": got},
                  open(out, "w"))
        print(f"[{label}] may_buy={may_buy} attached={attached}")


def spender():
    """One ended call adding to the allowance, at the same instant as others."""
    tid, start, label, out = sys.argv[2:6]
    with psycopg.connect(DSN, autocommit=True) as c:
        while time.time() < float(start):
            pass
        row = c.execute("select * from ita_consume_seconds(%s, %s)", (tid, 100)).fetchone()
        json.dump({"label": label, "total": row[1]}, open(out, "w"))


def parent():
    ok = []
    def chk(l, cond, d=""):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {l}{'  ' + str(d) if d else ''}")

    sql = open(M036).read()
    print(f"  036 sha256: {hashlib.sha256(open(M036,'rb').read()).hexdigest()}\n")
    T = lambda: str(uuid.uuid4())

    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("drop function if exists ita_consume_seconds(uuid, integer)")
        c.execute("drop table if exists ireland_temporary_access")
        chk("X0 the documented rollback leaves no table",
            c.execute("select count(*) from information_schema.tables where"
                      " table_name='ireland_temporary_access'").fetchone()[0] == 0)
        c.execute(sql)

        cols = sorted(r[0] for r in c.execute(
            "select column_name from information_schema.columns where"
            " table_name='ireland_temporary_access'").fetchall())
        chk("X1 exactly the reviewed columns", cols == [
            "access_started_at", "action_required_at", "created_at", "cutover_at",
            "e164", "provider_attempt_at", "provider_sid", "rejected_at",
            "released_at", "retirement_claimed_at", "seconds_used",
            "suspend_reason", "suspended_at", "tenant_id", "updated_at"], cols)
        kind = c.execute("select data_type, is_nullable, column_default from"
                         " information_schema.columns where"
                         " table_name='ireland_temporary_access'"
                         "   and column_name='provider_attempt_at'").fetchone()
        chk("X2 provider_attempt_at is a nullable timestamptz with no default",
            kind == ("timestamp with time zone", "YES", None), kind)
        su = c.execute("select data_type, is_nullable from information_schema.columns"
                       " where table_name='ireland_temporary_access'"
                       "   and column_name='seconds_used'").fetchone()
        chk("X3 seconds_used is a NOT NULL integer", su == ("integer", "NO"), su)
        chk("X4 row-level security is enabled",
            c.execute("select relrowsecurity from pg_class where"
                      " oid='ireland_temporary_access'::regclass").fetchone()[0] is True)
        chk("X5 no policies -- denied to anon and authenticated",
            c.execute("select count(*) from pg_policies where"
                      " tablename='ireland_temporary_access'").fetchone()[0] == 0)
        chk("X6 exactly one index: the primary key",
            c.execute("select count(*) from pg_indexes where"
                      " tablename='ireland_temporary_access'").fetchone()[0] == 1)
        c.execute(sql); c.execute(sql)
        chk("X7 replaying twice more changes nothing",
            len(c.execute("select column_name from information_schema.columns where"
                          " table_name='ireland_temporary_access'").fetchall()) == 15)

        # ── the provider-attempt invariant ────────────────────────────────
        t = T(); _tenant(c, t)
        c.execute(CLAIM, (t,))
        try:
            c.execute("update ireland_temporary_access set e164='+14165550100',"
                      " provider_sid='PN1' where tenant_id=%s", (t,))
            chk("X8 a number cannot be recorded without a recorded attempt", False,
                "update succeeded")
        except psycopg.Error as e:
            chk("X8 a number cannot be recorded without a recorded attempt",
                e.diag.constraint_name == "ita_number_implies_attempt_chk",
                e.diag.constraint_name)

        try:
            c.execute("update ireland_temporary_access set provider_attempt_at=now(),"
                      " e164='+14165550100' where tenant_id=%s", (t,))
            chk("X9 the number and its provider SID are one fact", False, "succeeded")
        except psycopg.Error as e:
            chk("X9 the number and its provider SID are one fact",
                e.diag.constraint_name == "ita_number_columns_agree_chk",
                e.diag.constraint_name)

        chk("X10 a claim with no attempt proves Twilio was never called",
            c.execute("select provider_attempt_at is null from"
                      " ireland_temporary_access where tenant_id=%s", (t,)).fetchone()[0])
        chk("X11 such a claim MAY be retaken", c.execute(RETAKE, (t,)).rowcount == 1)
        chk("X12 marking the attempt matches exactly one row",
            c.execute(MARK, (t,)).rowcount == 1)
        chk("X13 the attempt cannot be marked twice",
            c.execute(MARK, (t,)).rowcount == 0)
        chk("X14 an ATTEMPTED claim can NEVER be retaken",
            c.execute(RETAKE, (t,)).rowcount == 0)
        c.execute("update ireland_temporary_access set provider_attempt_at ="
                  " now() - interval '30 days' where tenant_id=%s", (t,))
        chk("X15 a 30-day-old unknown outcome STILL cannot be retaken",
            c.execute(RETAKE, (t,)).rowcount == 0)
        chk("X16 a positively reconciled number can be adopted",
            c.execute(ATTACH, ("+14165550100", "PN_a", t)).rowcount == 1)
        chk("X17 a second attach matches nothing -- no overwrite",
            c.execute(ATTACH, ("+14165550999", "PN_b", t)).rowcount == 0)
        chk("X18 the first number survives",
            c.execute("select e164 from ireland_temporary_access where tenant_id=%s",
                      (t,)).fetchone()[0] == "+14165550100")

        # ── the allowance ─────────────────────────────────────────────────
        chk("X19 a new lifecycle starts with no allowance consumed",
            c.execute("select seconds_used from ireland_temporary_access where"
                      " tenant_id=%s", (t,)).fetchone()[0] == 0)
        c.execute(CONSUME, (t, 1800)); c.execute(CONSUME, (t, 1500))
        chk("X20 consumption accumulates",
            c.execute("select seconds_used from ireland_temporary_access where"
                      " tenant_id=%s", (t,)).fetchone()[0] == 3300)
        try:
            c.execute("update ireland_temporary_access set seconds_used=-1 where"
                      " tenant_id=%s", (t,))
            chk("X21 the allowance cannot go negative", False, "succeeded")
        except psycopg.Error as e:
            chk("X21 the allowance cannot go negative",
                e.diag.constraint_name == "ita_seconds_used_chk", e.diag.constraint_name)

        # THE POINT OF THE TABLE: the number changes, the allowance does not.
        c.execute("update ireland_temporary_access set retirement_claimed_at=now(),"
                  " released_at=now() where tenant_id=%s", (t,))
        chk("X22 retiring the number does NOT reset the allowance",
            c.execute("select seconds_used from ireland_temporary_access where"
                      " tenant_id=%s", (t,)).fetchone()[0] == 3300)
        chk("X23 re-claiming the lifecycle row is a no-op, not a reset",
            c.execute(CLAIM, (t,)).rowcount == 0)
        chk("X24 the allowance is still spent after the re-claim",
            c.execute("select seconds_used from ireland_temporary_access where"
                      " tenant_id=%s", (t,)).fetchone()[0] == 3300)

        # ── suspension and release ────────────────────────────────────────
        t2 = T(); _tenant(c, t2)
        c.execute(CLAIM, (t2,))
        try:
            c.execute("update ireland_temporary_access set suspended_at=now()"
                      " where tenant_id=%s", (t2,))
            chk("X25 a suspension must say why", False, "succeeded")
        except psycopg.Error as e:
            chk("X25 a suspension must say why",
                e.diag.constraint_name == "ita_suspend_columns_agree_chk",
                e.diag.constraint_name)
        try:
            c.execute("update ireland_temporary_access set access_started_at=now()"
                      " where tenant_id=%s", (t2,))
            chk("X26 access cannot start before there is a number", False, "succeeded")
        except psycopg.Error as e:
            chk("X26 access cannot start before there is a number",
                e.diag.constraint_name == "ita_access_implies_number_chk",
                e.diag.constraint_name)
        try:
            c.execute("update ireland_temporary_access set released_at=now()"
                      " where tenant_id=%s", (t2,))
            chk("X27 a release is always the completion of a claim", False, "succeeded")
        except psycopg.Error as e:
            chk("X27 a release is always the completion of a claim",
                e.diag.constraint_name == "ita_release_implies_claim_chk",
                e.diag.constraint_name)

        # ── the tenant owns it ────────────────────────────────────────────
        c.execute("delete from tenants where id=%s", (t2,))
        chk("X28 deleting the tenant removes its access row",
            c.execute("select count(*) from ireland_temporary_access where"
                      " tenant_id=%s", (t2,)).fetchone()[0] == 0)

        # ── the allowance under REAL concurrency (Stage M) ────────────────
        # The failure this rules out: two calls ending together, both reading
        # 3540, both writing 3600, and 60 seconds of paid time vanishing.
        t4 = T(); _tenant(c, t4)
        c.execute(CLAIM, (t4,))
        start = time.time() + 1.5
        souts = [f"{TMP}/w9ihauto_spend_{i}.json" for i in range(6)]
        sprocs = [subprocess.Popen([sys.executable, __file__, "spender", t4,
                                    str(start), str(i), souts[i]]) for i in range(6)]
        for p in sprocs:
            p.wait()
        total = c.execute("select seconds_used from ireland_temporary_access"
                          " where tenant_id=%s", (t4,)).fetchone()[0]
        chk("X33 six concurrent 100-second calls total exactly 600",
            total == 600, total)
        totals = sorted(json.load(open(o))["total"] for o in souts)
        chk("X34 every increment returned a distinct running total",
            totals == [100, 200, 300, 400, 500, 600], totals)

        # ── real concurrency ──────────────────────────────────────────────
        t3 = T(); _tenant(c, t3)
        start = time.time() + 1.5
        outs = [f"{TMP}/w9ihauto_race_{i}.json" for i in range(4)]
        procs = [subprocess.Popen([sys.executable, __file__, "worker", t3,
                                   str(start), f"w{i}", outs[i]]) for i in range(4)]
        for p in procs:
            p.wait()
        res = [json.load(open(o)) for o in outs]
        chk("X29 exactly one worker was permitted to buy",
            sum(1 for r in res if r["may_buy"]) == 1, [r["may_buy"] for r in res])
        chk("X30 exactly one number was recorded",
            sum(r["attached"] for r in res) == 1, [r["attached"] for r in res])
        chk("X31 every worker that read a value saw the same number",
            len({r["saw"] for r in res if r["saw"]}) == 1,
            sorted({r["saw"] for r in res if r["saw"]}))
        chk("X32 exactly one lifecycle row exists",
            c.execute("select count(*) from ireland_temporary_access where"
                      " tenant_id=%s", (t3,)).fetchone()[0] == 1)

    n = sum(ok)
    print(f"\n  STAGE X: {n}/{len(ok)} passed" + ("  ALL PASS" if n == len(ok) else "  FAILURES"))
    return 0 if n == len(ok) else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker()
    elif len(sys.argv) > 1 and sys.argv[1] == "spender":
        spender()
    else:
        sys.exit(parent())
