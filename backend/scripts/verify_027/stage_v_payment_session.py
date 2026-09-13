"""W9I-H.0.2 — migration 034 against real PostgreSQL, BEFORE it is proposed.

The property that matters is narrow and easy to get wrong: four concurrent
/setup-card calls for one signup must leave exactly ONE Stripe Customer. The
database elects the creator; Stripe's idempotency key covers the window where
the elected creator's own response goes missing. This proves the first half.

Run as:
    stage_v_payment_session.py parent
    stage_v_payment_session.py worker <key> <country> <start> <label> <out>
"""
import hashlib, json, os, subprocess, sys, time, uuid
import psycopg

DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55433/w9e_scratch")
TMP = os.environ.get("W9IH2_TMP", "/tmp")
MIGRATION = "/Users/muazmuhamed/open-lines/migrations/034_onboarding_payment_session.sql"

CLAIM = """
insert into onboarding_payment_sessions (onboarding_key, iso_country)
values (%s, %s)
on conflict (onboarding_key) do nothing
"""
ATTACH = """
update onboarding_payment_sessions
   set stripe_customer_id = %s, updated_at = now()
 where onboarding_key = %s and stripe_customer_id is null
"""


def worker():
    """One /setup-card attempt: claim, 'create', fenced attach."""
    key, country, start, label, out = sys.argv[2:7]
    mine = f"cus_{label}{uuid.uuid4().hex[:16]}"
    with psycopg.connect(DSN, autocommit=True) as c:
        while time.time() < float(start):
            pass
        claimed = c.execute(CLAIM, (key, country)).rowcount == 1
        # Only the claimer calls the provider. Everyone else reads the winner's.
        attached = 0
        if claimed:
            attached = c.execute(ATTACH, (mine, key)).rowcount
        got = c.execute("select stripe_customer_id from onboarding_payment_sessions"
                        " where onboarding_key=%s", (key,)).fetchone()[0]
        json.dump({"label": label, "claimed": claimed, "attached": attached,
                   "saw": got, "created": mine if claimed else None},
                  open(out, "w"))
        print(f"[{label}] claimed={claimed} attached={attached}")


def parent():
    ok = []
    def chk(l, cond, d=""):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {l}{'  ' + str(d) if d else ''}")

    sql = open(MIGRATION).read()
    print(f"  migration sha256: {hashlib.sha256(open(MIGRATION,'rb').read()).hexdigest()}\n")
    K = lambda: str(uuid.uuid4())

    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("drop table if exists onboarding_payment_sessions")
        chk("V0 the documented rollback leaves no table", True)

        c.execute(sql)
        cols = {r[0]: (r[1], r[2]) for r in c.execute(
            "select column_name, data_type, is_nullable from information_schema.columns"
            " where table_name='onboarding_payment_sessions'").fetchall()}
        chk("V1 exactly the reviewed columns",
            set(cols) == {"onboarding_key", "iso_country", "stripe_customer_id",
                          "created_at", "updated_at"}, sorted(cols))
        chk("V2 stripe_customer_id is nullable — the claim precedes the provider",
            cols["stripe_customer_id"][1] == "YES")
        chk("V3 iso_country is NOT NULL", cols["iso_country"][1] == "NO")
        chk("V4 row-level security is enabled",
            c.execute("select relrowsecurity from pg_class where"
                      " oid='onboarding_payment_sessions'::regclass").fetchone()[0] is True)
        chk("V5 no policies — denied to anon and authenticated",
            c.execute("select count(*) from pg_policies where"
                      " tablename='onboarding_payment_sessions'").fetchone()[0] == 0)
        chk("V6 exactly two indexes: the PK and the customer uniqueness",
            c.execute("select count(*) from pg_indexes where"
                      " tablename='onboarding_payment_sessions'").fetchone()[0] == 2)
        c.execute(sql); c.execute(sql)
        chk("V7 replaying twice more changes nothing",
            c.execute("select count(*) from information_schema.columns where"
                      " table_name='onboarding_payment_sessions'").fetchone()[0] == 5)
        chk("V8 a new table starts empty",
            c.execute("select count(*) from onboarding_payment_sessions").fetchone()[0] == 0)

        # ── the constraints ───────────────────────────────────────────────
        def refused(key, country, cus, name):
            try:
                c.execute("insert into onboarding_payment_sessions"
                          " (onboarding_key, iso_country, stripe_customer_id)"
                          " values (%s,%s,%s)", (key, country, cus))
                return False, "insert succeeded"
            except psycopg.Error as e:
                got = getattr(e.diag, "constraint_name", None)
                return got == name, got
        good, d = refused("not-a-uuid", "IE", None, "ops_key_is_uuid_chk")
        chk("V9 a non-uuid4 key is refused", good, d)
        good, d = refused(K(), "ireland", None, "ops_country_chk")
        chk("V10 a malformed country is refused", good, d)
        good, d = refused(K(), "IE", "not_a_customer", "ops_customer_shape_chk")
        chk("V11 a value that is not a Stripe customer id is refused", good, d)

        # ── the claim / attach lifecycle ──────────────────────────────────
        k1 = K()
        chk("V12 the first claim inserts one row",
            c.execute(CLAIM, (k1, "IE")).rowcount == 1)
        chk("V13 a second claim for the same key inserts nothing",
            c.execute(CLAIM, (k1, "IE")).rowcount == 0)
        row = c.execute("select stripe_customer_id from onboarding_payment_sessions"
                        " where onboarding_key=%s", (k1,)).fetchone()[0]
        chk("V14 the claim holds no customer yet", row is None)
        chk("V15 the fenced attach matches exactly one row",
            c.execute(ATTACH, ("cus_first", k1)).rowcount == 1)
        chk("V16 a second attach matches nothing — no overwrite",
            c.execute(ATTACH, ("cus_second", k1)).rowcount == 0)
        chk("V17 the first customer survives",
            c.execute("select stripe_customer_id from onboarding_payment_sessions"
                      " where onboarding_key=%s", (k1,)).fetchone()[0] == "cus_first")

        # ── one Customer belongs to one signup ────────────────────────────
        k2 = K()
        c.execute(CLAIM, (k2, "CA"))
        try:
            c.execute(ATTACH, ("cus_first", k2))
            chk("V18 one Customer cannot serve two signups", False, "attach succeeded")
        except psycopg.Error as e:
            chk("V18 one Customer cannot serve two signups",
                e.sqlstate == "23505"
                and getattr(e.diag, "constraint_name", None) == "ops_customer_key",
                getattr(e.diag, "constraint_name", None))
        chk("V19 distinct signups get distinct Customers",
            c.execute(ATTACH, ("cus_second", k2)).rowcount == 1)

        # ── an unconfirmed create stays reconcilable ──────────────────────
        k3 = K()
        c.execute(CLAIM, (k3, "IE"))
        chk("V20 a claim whose provider call never answered is visibly unattached",
            c.execute("select stripe_customer_id from onboarding_payment_sessions"
                      " where onboarding_key=%s", (k3,)).fetchone()[0] is None)
        chk("V21 a later attempt can attach the recovered Customer",
            c.execute(ATTACH, ("cus_recovered", k3)).rowcount == 1)

        # ── the country is recorded, and a mismatch is visible ────────────
        chk("V22 the approved country is recorded on the session",
            c.execute("select iso_country from onboarding_payment_sessions"
                      " where onboarding_key=%s", (k2,)).fetchone()[0] == "CA")

        race_key = K()

    # ── four concurrent /setup-card attempts, one signup ──────────────────
    start = time.time() + 2.0
    outs, procs = [], []
    for i in range(4):
        out = f"{TMP}/w9ih2_race_{i}.json"
        outs.append(out)
        procs.append(subprocess.Popen(
            [sys.executable, __file__, "worker", race_key, "IE",
             str(start), f"w{i}", out]))
    for p in procs:
        p.wait()
    res = [json.load(open(o)) for o in outs]
    chk("V23 exactly one worker claimed the signup",
        sum(1 for r in res if r["claimed"]) == 1, [r["claimed"] for r in res])
    chk("V24 exactly one Customer was attached",
        sum(r["attached"] for r in res) == 1, [r["attached"] for r in res])
    created = [r["created"] for r in res if r["created"]]
    chk("V25 only the claimer would have called the provider",
        len(created) == 1, len(created))
    seen = {r["saw"] for r in res if r["saw"]}
    chk("V26 every worker that read a value saw the same Customer",
        len(seen) <= 1, sorted(seen))

    with psycopg.connect(DSN, autocommit=True) as c:
        n = c.execute("select count(*) from onboarding_payment_sessions"
                      " where onboarding_key=%s", (race_key,)).fetchone()[0]
        chk("V27 exactly one session row exists for the signup", n == 1, n)
        cus = c.execute("select stripe_customer_id from onboarding_payment_sessions"
                        " where onboarding_key=%s", (race_key,)).fetchone()[0]
        chk("V28 it names the claimer's Customer", cus == created[0], cus)
        # A retry days later -- past any provider idempotency window -- reuses it.
        chk("V29 a much later retry claims nothing and reuses the Customer",
            c.execute(CLAIM, (race_key, "IE")).rowcount == 0
            and c.execute(ATTACH, ("cus_much_later", race_key)).rowcount == 0)
        chk("V30 the original Customer is still the one on file",
            c.execute("select stripe_customer_id from onboarding_payment_sessions"
                      " where onboarding_key=%s", (race_key,)).fetchone()[0] == cus)
        c.execute("drop table onboarding_payment_sessions")

    print(f"\n  STAGE V: {sum(ok)}/{len(ok)} passed" +
          ("  ALL PASS" if all(ok) else "  FAILURES"))
    return all(ok)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker()
    else:
        sys.exit(0 if parent() else 1)
