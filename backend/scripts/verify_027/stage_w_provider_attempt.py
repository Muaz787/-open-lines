"""W9I-H.0.2R — migration 035 against real PostgreSQL, BEFORE it is proposed.

The property it exists for: an unknown provider outcome must never find its way
back to "safe to create". Everything else here is in service of proving that one
transition is unreachable.

Run as:
    stage_w_provider_attempt.py parent
    stage_w_provider_attempt.py worker <key> <start> <label> <out>
"""
import hashlib, json, os, subprocess, sys, time, uuid
import psycopg

DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55433/w9e_scratch")
TMP = os.environ.get("W9IH2_TMP", "/tmp")
M034 = "/Users/muazmuhamed/open-lines/migrations/034_onboarding_payment_session.sql"
M035 = "/Users/muazmuhamed/open-lines/migrations/035_payment_session_provider_attempt.sql"

CLAIM = """
insert into onboarding_payment_sessions (onboarding_key, iso_country)
values (%s,%s) on conflict (onboarding_key) do nothing
"""
#: Written immediately BEFORE stripe.Customer.create, and only from a session
#: that has never attempted one.
MARK = """
update onboarding_payment_sessions
   set provider_attempt_at = now(), updated_at = now()
 where onboarding_key = %s and provider_attempt_at is null
"""
ATTACH = """
update onboarding_payment_sessions
   set stripe_customer_id = %s, updated_at = now()
 where onboarding_key = %s and stripe_customer_id is null
   and provider_attempt_at is not null
"""
#: A stale claim may only be retaken when it PROVES Stripe was never called.
RETAKE = """
update onboarding_payment_sessions
   set updated_at = now()
 where onboarding_key = %s
   and provider_attempt_at is null
   and stripe_customer_id is null
"""


def worker():
    key, start, label, out = sys.argv[2:6]
    mine = f"cus_{label}{uuid.uuid4().hex[:14]}"
    with psycopg.connect(DSN, autocommit=True) as c:
        while time.time() < float(start):
            pass
        c.execute(CLAIM, (key, "IE"))
        # Only a worker that wins the MARK may call the provider.
        may_create = c.execute(MARK, (key,)).rowcount == 1
        attached = c.execute(ATTACH, (mine, key)).rowcount if may_create else 0
        got = c.execute("select stripe_customer_id from onboarding_payment_sessions"
                        " where onboarding_key=%s", (key,)).fetchone()[0]
        json.dump({"label": label, "may_create": may_create, "attached": attached,
                   "saw": got}, open(out, "w"))
        print(f"[{label}] may_create={may_create} attached={attached}")


def parent():
    ok = []
    def chk(l, cond, d=""):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {l}{'  ' + str(d) if d else ''}")

    print(f"  034 sha256: {hashlib.sha256(open(M034,'rb').read()).hexdigest()}")
    print(f"  035 sha256: {hashlib.sha256(open(M035,'rb').read()).hexdigest()}\n")
    K = lambda: str(uuid.uuid4())

    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("drop table if exists onboarding_payment_sessions")
        c.execute(open(M034).read())
        before = c.execute("select count(*) from information_schema.columns where"
                           " table_name='onboarding_payment_sessions'").fetchone()[0]
        chk("W0 034 alone cannot express a provider attempt",
            c.execute("select count(*) from information_schema.columns"
                      " where table_name='onboarding_payment_sessions'"
                      "   and column_name='provider_attempt_at'").fetchone()[0] == 0)

        sql = open(M035).read()
        c.execute(sql)
        chk("W1 035 adds exactly one column",
            c.execute("select count(*) from information_schema.columns where"
                      " table_name='onboarding_payment_sessions'").fetchone()[0] == before + 1)
        kind = c.execute("select data_type, is_nullable, column_default from"
                         " information_schema.columns where"
                         " table_name='onboarding_payment_sessions'"
                         "   and column_name='provider_attempt_at'").fetchone()
        chk("W2 it is a nullable timestamptz with no default",
            kind == ("timestamp with time zone", "YES", None), kind)
        chk("W3 row-level security is still enabled",
            c.execute("select relrowsecurity from pg_class where"
                      " oid='onboarding_payment_sessions'::regclass").fetchone()[0] is True)
        chk("W4 still no policies",
            c.execute("select count(*) from pg_policies where"
                      " tablename='onboarding_payment_sessions'").fetchone()[0] == 0)
        chk("W5 no index was added",
            c.execute("select count(*) from pg_indexes where"
                      " tablename='onboarding_payment_sessions'").fetchone()[0] == 2)
        c.execute(sql); c.execute(sql)
        chk("W6 replaying twice more changes nothing",
            c.execute("select count(*) from information_schema.columns where"
                      " table_name='onboarding_payment_sessions'").fetchone()[0] == before + 1)

        # ── the invariant ─────────────────────────────────────────────────
        k = K()
        c.execute(CLAIM, (k, "IE"))
        try:
            c.execute("update onboarding_payment_sessions set stripe_customer_id='cus_x'"
                      " where onboarding_key=%s", (k,))
            chk("W7 a Customer cannot be attached without a recorded attempt",
                False, "update succeeded")
        except psycopg.Error as e:
            chk("W7 a Customer cannot be attached without a recorded attempt",
                getattr(e.diag, "constraint_name", None)
                == "ops_attach_implies_attempt_chk",
                getattr(e.diag, "constraint_name", None))

        # ── state 2: never called. Provably safe to retake. ───────────────
        chk("W8 a claim with no attempt proves Stripe was never called",
            c.execute("select provider_attempt_at is null from"
                      " onboarding_payment_sessions where onboarding_key=%s",
                      (k,)).fetchone()[0] is True)
        chk("W9 such a claim MAY be retaken", c.execute(RETAKE, (k,)).rowcount == 1)

        # ── state 4: attempted, outcome unknown. Never again. ─────────────
        chk("W10 marking an attempt matches exactly one row",
            c.execute(MARK, (k,)).rowcount == 1)
        chk("W11 the attempt cannot be marked twice",
            c.execute(MARK, (k,)).rowcount == 0)
        chk("W12 an ATTEMPTED claim can NEVER be retaken — state 4 has no route "
            "back to state 1", c.execute(RETAKE, (k,)).rowcount == 0)
        # ...and time passing changes nothing.
        c.execute("update onboarding_payment_sessions"
                  " set provider_attempt_at = now() - interval '30 days',"
                  "     created_at = now() - interval '30 days'"
                  " where onboarding_key=%s", (k,))
        chk("W13 a 30-day-old unknown outcome STILL cannot be retaken",
            c.execute(RETAKE, (k,)).rowcount == 0)
        chk("W14 it is still unattached and visibly unresolved",
            c.execute("select stripe_customer_id is null and provider_attempt_at"
                      " is not null from onboarding_payment_sessions"
                      " where onboarding_key=%s", (k,)).fetchone()[0] is True)

        # ── recovery: a positively identified Customer may be adopted ─────
        chk("W15 a recovered Customer can be adopted by the fenced attach",
            c.execute(ATTACH, ("cus_recovered", k)).rowcount == 1)
        chk("W16 a second attach matches nothing",
            c.execute(ATTACH, ("cus_other", k)).rowcount == 0)
        chk("W17 the recovered Customer survives",
            c.execute("select stripe_customer_id from onboarding_payment_sessions"
                      " where onboarding_key=%s", (k,)).fetchone()[0] == "cus_recovered")
        chk("W18 an attached session can never be retaken",
            c.execute(RETAKE, (k,)).rowcount == 0)

        # ── 034's guarantees survive ──────────────────────────────────────
        k2 = K()
        c.execute(CLAIM, (k2, "CA"))
        c.execute(MARK, (k2,))
        try:
            c.execute(ATTACH, ("cus_recovered", k2))
            chk("W19 one Customer still cannot serve two signups", False,
                "attach succeeded")
        except psycopg.Error as e:
            chk("W19 one Customer still cannot serve two signups",
                getattr(e.diag, "constraint_name", None) == "ops_customer_key",
                getattr(e.diag, "constraint_name", None))
        chk("W20 distinct signups still get distinct Customers",
            c.execute(ATTACH, ("cus_second", k2)).rowcount == 1)

        race = K()

    # ── four concurrent /setup-card attempts ──────────────────────────────
    start = time.time() + 2.0
    outs, procs = [], []
    for i in range(4):
        out = f"{TMP}/w9ih2r_race_{i}.json"
        outs.append(out)
        procs.append(subprocess.Popen(
            [sys.executable, __file__, "worker", race, str(start), f"w{i}", out]))
    for p in procs:
        p.wait()
    res = [json.load(open(o)) for o in outs]
    chk("W21 exactly one worker was allowed to call the provider",
        sum(1 for r in res if r["may_create"]) == 1, [r["may_create"] for r in res])
    chk("W22 exactly one Customer was attached",
        sum(r["attached"] for r in res) == 1, [r["attached"] for r in res])
    seen = {r["saw"] for r in res if r["saw"]}
    chk("W23 every worker that read a value saw the same Customer",
        len(seen) <= 1, sorted(seen))

    with psycopg.connect(DSN, autocommit=True) as c:
        n = c.execute("select count(*) from onboarding_payment_sessions"
                      " where onboarding_key=%s", (race,)).fetchone()[0]
        chk("W24 exactly one session row exists", n == 1, n)
        chk("W25 a much later retry can neither retake nor re-attach",
            c.execute(RETAKE, (race,)).rowcount == 0
            and c.execute(ATTACH, ("cus_way_later", race)).rowcount == 0)
        c.execute("drop table onboarding_payment_sessions")

    print(f"\n  STAGE W: {sum(ok)}/{len(ok)} passed" +
          ("  ALL PASS" if all(ok) else "  FAILURES"))
    return all(ok)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker()
    else:
        sys.exit(0 if parent() else 1)
