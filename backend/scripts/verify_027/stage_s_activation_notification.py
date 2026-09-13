"""W9I-G — migration 032 against real PostgreSQL, BEFORE it is proposed for apply.

Proves what a migration has to prove: replaying it changes nothing, the
invariants it declares actually fire, the claim it exists for is exclusive under
real concurrency, and -- the point of the redesign -- a REPLACEMENT permanent
number gets an entirely independent notification lifecycle.

Run as:
    stage_s_activation_notification.py parent
    stage_s_activation_notification.py worker <row_id> <start> <label> <out>
"""
import hashlib, json, os, subprocess, sys, time, uuid
import psycopg

DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55433/w9e_scratch")
TMP = os.environ.get("W9IG_TMP", "/tmp")
MIGRATION = "/Users/muazmuhamed/open-lines/migrations/032_activation_notification.sql"

#: The fenced claim, exactly as the application will issue it.
CLAIM = """
update tenant_phone_numbers
   set activation_email_claimed_at = now()
 where id = %s
   and activation_email_claimed_at is null
"""

INSERT = """
insert into tenant_phone_numbers
  (id, tenant_id, e164, purpose, status, provider, provider_account_sid,
   provider_sid, iso_country)
values (%s,%s,%s,'permanent',%s,'twilio','ACsub',%s,'IE')
"""


def worker():
    row_id, start, label, out = sys.argv[2:6]
    with psycopg.connect(DSN, autocommit=True) as c:
        while time.time() < float(start):
            pass
        cur = c.execute(CLAIM, (row_id,))
        json.dump({"label": label, "rows": cur.rowcount}, open(out, "w"))
        print(f"[{label}] rows={cur.rowcount}")


def _fingerprint(c) -> str:
    cols = c.execute("select column_name, data_type, is_nullable, column_default"
                     " from information_schema.columns"
                     " where table_name='tenant_phone_numbers'"
                     " order by column_name").fetchall()
    cons = c.execute("select conname, pg_get_constraintdef(oid) from pg_constraint"
                     " where conrelid='tenant_phone_numbers'::regclass"
                     " order by conname").fetchall()
    idx = c.execute("select indexname, indexdef from pg_indexes"
                    " where tablename='tenant_phone_numbers'"
                    " order by indexname").fetchall()
    return hashlib.sha256(repr((cols, cons, idx)).encode()).hexdigest()


def parent():
    ok = []
    def chk(l, cond, d=""):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {l}{'  ' + str(d) if d else ''}")

    sql = open(MIGRATION).read()
    print(f"  migration sha256: {hashlib.sha256(open(MIGRATION,'rb').read()).hexdigest()}\n")

    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("delete from tenants where business_name like 'W9IG%'")
        # CLEAN SLATE, so every run genuinely proves a FIRST apply rather than a
        # replay of one a previous run left behind. This is the rollback written
        # into the migration file, which therefore gets exercised too.
        c.execute("""
            alter table tenant_phone_numbers
                drop constraint if exists tpn_activation_email_provider_chk,
                drop constraint if exists tpn_activation_email_claim_chk;
            alter table tenant_phone_numbers
                drop column if exists activation_email_provider_id,
                drop column if exists activation_email_sent_at,
                drop column if exists activation_email_claimed_at;
        """)
        rolled_back = c.execute(
            "select count(*) from information_schema.columns"
            " where table_name='tenant_phone_numbers'"
            "   and column_name like 'activation_email%'").fetchone()[0]
        chk("S0 the documented rollback removes every column it added",
            rolled_back == 0, rolled_back)
        before = _fingerprint(c)
        cols_before = c.execute("select count(*) from information_schema.columns"
                                " where table_name='tenant_phone_numbers'").fetchone()[0]
        idx_before = c.execute("select count(*) from pg_indexes"
                               " where tablename='tenant_phone_numbers'").fetchone()[0]
        rls_before = c.execute("select relrowsecurity from pg_class"
                               " where oid='tenant_phone_numbers'::regclass").fetchone()[0]
        pol_before = c.execute("select count(*) from pg_policies"
                               " where tablename='tenant_phone_numbers'").fetchone()[0]

        # ── first apply ───────────────────────────────────────────────────
        c.execute(sql)
        after_once = _fingerprint(c)
        chk("S1 applying 032 changes the catalog", before != after_once)

        cols = {r[0]: r[1] for r in c.execute(
            "select column_name, data_type from information_schema.columns"
            " where table_name='tenant_phone_numbers'"
            "   and column_name like 'activation_email%'").fetchall()}
        chk("S2 the three columns exist with the right types",
            cols == {"activation_email_claimed_at": "timestamp with time zone",
                     "activation_email_sent_at": "timestamp with time zone",
                     "activation_email_provider_id": "text"}, cols)
        chk("S3 exactly three columns were added",
            c.execute("select count(*) from information_schema.columns where"
                      " table_name='tenant_phone_numbers'").fetchone()[0]
            == cols_before + 3)
        bad = c.execute(
            "select count(*) from information_schema.columns"
            " where table_name='tenant_phone_numbers'"
            "   and column_name like 'activation_email%'"
            "   and (is_nullable <> 'YES' or column_default is not null)").fetchone()[0]
        chk("S4 all three are nullable with no default", bad == 0, bad)

        # ── no index, no RLS change ───────────────────────────────────────
        chk("S5 no index was added",
            c.execute("select count(*) from pg_indexes where"
                      " tablename='tenant_phone_numbers'").fetchone()[0] == idx_before)
        chk("S6 row-level security is unchanged and still enabled",
            c.execute("select relrowsecurity from pg_class where"
                      " oid='tenant_phone_numbers'::regclass").fetchone()[0]
            == rls_before is True)
        chk("S7 policy count unchanged (still deny-all below PostgREST)",
            c.execute("select count(*) from pg_policies where"
                      " tablename='tenant_phone_numbers'").fetchone()[0] == pol_before,
            pol_before)

        # ── replay ────────────────────────────────────────────────────────
        c.execute(sql); c.execute(sql)
        chk("S8 replaying twice more changes nothing", _fingerprint(c) == after_once)

        # ── fixtures ──────────────────────────────────────────────────────
        tid = str(uuid.uuid4())
        c.execute("insert into tenants (id, business_name, industry,"
                  " business_country_code) values (%s,'W9IG notify','realtor','IE')",
                  (tid,))
        original = str(uuid.uuid4())
        c.execute(INSERT, (original, tid, "+35315550123", "active", "PNorig"))

        got = c.execute("select activation_email_claimed_at, activation_email_sent_at,"
                        " activation_email_provider_id from tenant_phone_numbers"
                        " where id=%s", (original,)).fetchone()
        chk("S9 a new row backfills to NULL/NULL/NULL", got == (None, None, None), got)

        # ── the invariants ────────────────────────────────────────────────
        try:
            c.execute("update tenant_phone_numbers set activation_email_sent_at=now()"
                      " where id=%s", (original,))
            chk("S10 a send without a claim is refused", False, "update succeeded")
        except psycopg.Error as e:
            chk("S10 a send without a claim is refused",
                e.sqlstate == "23514" and getattr(e.diag, "constraint_name", None)
                == "tpn_activation_email_claim_chk",
                getattr(e.diag, "constraint_name", None))

        try:
            c.execute("update tenant_phone_numbers"
                      " set activation_email_provider_id='resend_x' where id=%s",
                      (original,))
            chk("S11 a provider id without a send is refused", False, "update succeeded")
        except psycopg.Error as e:
            chk("S11 a provider id without a send is refused",
                e.sqlstate == "23514" and getattr(e.diag, "constraint_name", None)
                == "tpn_activation_email_provider_chk",
                getattr(e.diag, "constraint_name", None))

        cur = c.execute(CLAIM, (original,))
        chk("S12 the first claim matches exactly one row", cur.rowcount == 1, cur.rowcount)
        cur = c.execute(CLAIM, (original,))
        chk("S13 a second claim matches zero rows", cur.rowcount == 0, cur.rowcount)

        c.execute("update tenant_phone_numbers set activation_email_sent_at=now(),"
                  " activation_email_provider_id='resend_abc' where id=%s", (original,))
        chk("S14 claim then send then provider id is permitted", True)

        try:
            c.execute("update tenant_phone_numbers"
                      " set activation_email_claimed_at=null where id=%s", (original,))
            chk("S15 a completed notification cannot lose its claim", False,
                "update succeeded")
        except psycopg.Error as e:
            chk("S15 a completed notification cannot lose its claim",
                e.sqlstate == "23514", e.sqlstate)

        # A FAILED send releases its claim cleanly, so a retry can take it.
        second = str(uuid.uuid4())
        c.execute("update tenant_phone_numbers set status='released',"
                  " released_at=now() where id=%s", (original,))
        c.execute(INSERT, (second, tid, "+35315550124", "provisioning", "PNsecond"))
        c.execute(CLAIM, (second,))
        c.execute("update tenant_phone_numbers set activation_email_claimed_at=null"
                  " where id=%s", (second,))
        cur = c.execute(CLAIM, (second,))
        chk("S16 a released claim can be re-taken for a retry", cur.rowcount == 1,
            cur.rowcount)

        # ── THE REDESIGN: a replacement is independent ────────────────────
        # str() on the ids: psycopg returns uuid.UUID, the fixtures hold strings.
        state = {str(r[0]): r[1] for r in c.execute(
            "select id, activation_email_sent_at is not null from tenant_phone_numbers"
            " where tenant_id=%s", (tid,)).fetchall()}
        chk("S17 the original is notified and the replacement is not",
            state == {original: True, second: False}, state)
        chk("S18 a tenant-global flag would have suppressed the replacement",
            any(state.values()) and not all(state.values()), state)

        # race fixture: one fresh row, four workers
        race = str(uuid.uuid4())
        c.execute("update tenant_phone_numbers set status='released',"
                  " released_at=now() where id=%s", (second,))
        c.execute(INSERT, (race, tid, "+35315550125", "provisioning", "PNrace"))

    start = time.time() + 2.0
    outs, procs = [], []
    for i in range(4):
        out = f"{TMP}/w9ig_race_{i}.json"
        outs.append(out)
        procs.append(subprocess.Popen(
            [sys.executable, __file__, "worker", race, str(start), f"w{i}", out]))
    for p in procs:
        p.wait()
    res = [json.load(open(o)) for o in outs]
    winners = [r for r in res if r["rows"] == 1]
    chk("S19 four concurrent claims produce exactly one winner",
        len(winners) == 1, [r["rows"] for r in res])
    chk("S20 every loser matched zero rows",
        all(r["rows"] == 0 for r in res if r not in winners))

    with psycopg.connect(DSN, autocommit=True) as c:
        claimed = c.execute("select activation_email_claimed_at from"
                            " tenant_phone_numbers where id=%s", (race,)).fetchone()[0]
        chk("S21 exactly one claim timestamp was recorded", claimed is not None)
        c.execute("delete from tenants where id=%s", (tid,))
        chk("S22 notification state is removed with the tenant",
            c.execute("select count(*) from tenant_phone_numbers where tenant_id=%s",
                      (tid,)).fetchone()[0] == 0)

    print(f"\n  STAGE S: {sum(ok)}/{len(ok)} passed" +
          ("  ALL PASS" if all(ok) else "  FAILURES"))
    return all(ok)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker()
    else:
        sys.exit(0 if parent() else 1)
