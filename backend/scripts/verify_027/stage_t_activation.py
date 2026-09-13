"""W9I-G — the activation lifecycle under real OS-level concurrency.

Two races decide whether a customer is charged twice or emailed twice, and
neither can be settled by unit tests: the promotion CAS and the notification
claim. Both are raced here by independent processes against real PostgreSQL.

Run as:
    stage_t_activation.py parent
    stage_t_activation.py worker <promote|notify> <row_id> <tenant> <start> <label> <out>
"""
import hashlib, json, os, subprocess, sys, time, uuid
import psycopg

DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55433/w9e_scratch")
TMP = os.environ.get("W9IG_TMP", "/tmp")
MIGRATION = "/Users/muazmuhamed/open-lines/migrations/032_activation_notification.sql"

E164 = "+35315550123"
PN = "PNactivate"
SUB = "ACsub"

PROMOTE = """
update tenant_phone_numbers
   set status='active', activated_at=now(), activated_at_source='promotion'
 where id=%s and tenant_id=%s and e164=%s
   and provider_sid=%s and provider_account_sid=%s
   and status='provisioning'
"""
CLAIM = """
update tenant_phone_numbers
   set activation_email_claimed_at = now()
 where id=%s and activation_email_claimed_at is null
"""


def worker():
    kind, row_id, tenant, start, label, out = sys.argv[2:8]
    with psycopg.connect(DSN, autocommit=True) as c:
        while time.time() < float(start):
            pass
        if kind == "promote":
            cur = c.execute(PROMOTE, (row_id, tenant, E164, PN, SUB))
        else:
            cur = c.execute(CLAIM, (row_id,))
        json.dump({"label": label, "rows": cur.rowcount}, open(out, "w"))
        print(f"[{label}/{kind}] rows={cur.rowcount}")


def _race(kind, row_id, tenant, chk, n=4):
    start = time.time() + 2.0
    outs, procs = [], []
    for i in range(n):
        out = f"{TMP}/w9ig_{kind}_{i}.json"
        outs.append(out)
        procs.append(subprocess.Popen(
            [sys.executable, __file__, "worker", kind, row_id, tenant,
             str(start), f"w{i}", out]))
    for p in procs:
        p.wait()
    return [json.load(open(o)) for o in outs]


def parent():
    ok = []
    def chk(l, cond, d=""):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {l}{'  ' + str(d) if d else ''}")

    print(f"  migration sha256: {hashlib.sha256(open(MIGRATION,'rb').read()).hexdigest()}\n")

    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("delete from tenants where business_name like 'W9IGT%'")
        c.execute(open(MIGRATION).read())       # idempotent
        tid = str(uuid.uuid4())
        c.execute("insert into tenants (id, business_name, industry,"
                  " business_country_code) values (%s,'W9IGT act','realtor','IE')", (tid,))
        rid = str(uuid.uuid4())
        c.execute("insert into tenant_phone_numbers (id, tenant_id, e164, purpose,"
                  " status, provider, provider_account_sid, provider_sid, iso_country)"
                  " values (%s,%s,%s,'permanent','provisioning','twilio',%s,%s,'IE')",
                  (rid, tid, E164, SUB, PN))
        # the transitional state W9I-F leaves behind
        c.execute("insert into tenant_phone_numbers (id, tenant_id, e164, purpose,"
                  " status, provider, provider_account_sid, provider_sid, iso_country)"
                  " values (%s,%s,'+442071234567','temporary_test','active','twilio',"
                  "%s,'PNtemp','GB')", (str(uuid.uuid4()), tid, SUB))

    # ── RACE 1: promotion ─────────────────────────────────────────────────
    res = _race("promote", rid, tid, chk)
    winners = [r for r in res if r["rows"] == 1]
    chk("T1 four concurrent promotions produce exactly one winner",
        len(winners) == 1, [r["rows"] for r in res])
    chk("T2 every loser changed zero rows",
        all(r["rows"] == 0 for r in res if r not in winners))

    with psycopg.connect(DSN, autocommit=True) as c:
        row = c.execute("select status, activated_at, activated_at_source"
                        " from tenant_phone_numbers where id=%s", (rid,)).fetchone()
        chk("T3 the number is active exactly once", row[0] == "active", row[0])
        chk("T4 activation provenance is recorded as a promotion",
            row[1] is not None and row[2] == "promotion", row[2])
        # A second promotion attempt now matches nothing -- the prior status is
        # part of the fence, so nobody can restamp the activation.
        cur = c.execute(PROMOTE, (rid, tid, E164, PN, SUB))
        chk("T5 an already-active row cannot be re-promoted", cur.rowcount == 0,
            cur.rowcount)

        # the temporary line is untouched by promotion
        t = c.execute("select status from tenant_phone_numbers where tenant_id=%s"
                      " and purpose='temporary_test'", (tid,)).fetchone()[0]
        chk("T6 the temporary number is untouched by promotion", t == "active", t)
        both = c.execute("select count(*) from tenant_phone_numbers where tenant_id=%s"
                         " and status in ('active','retiring')", (tid,)).fetchone()[0]
        chk("T7 both numbers may ring during the grace window", both == 2, both)

        # a stale worker holding the OLD identity cannot touch a replacement
        cur = c.execute(PROMOTE, (rid, tid, "+35399999999", PN, SUB))
        chk("T8 a stale worker with the wrong E.164 matches nothing",
            cur.rowcount == 0, cur.rowcount)

    # ── RACE 2: the notification claim ───────────────────────────────────
    res = _race("notify", rid, tid, chk)
    winners = [r for r in res if r["rows"] == 1]
    chk("T9 four concurrent notification claims produce exactly one winner",
        len(winners) == 1, [r["rows"] for r in res])
    chk("T10 every loser changed zero rows",
        all(r["rows"] == 0 for r in res if r not in winners))

    with psycopg.connect(DSN, autocommit=True) as c:
        claimed = c.execute("select activation_email_claimed_at from"
                            " tenant_phone_numbers where id=%s", (rid,)).fetchone()[0]
        chk("T11 exactly one claim timestamp exists", claimed is not None)
        c.execute("update tenant_phone_numbers set activation_email_sent_at=now(),"
                  " activation_email_provider_id='resend_ok' where id=%s", (rid,))
        # Once sent, the confirm fence matches nothing -- no second send recorded.
        cur = c.execute("update tenant_phone_numbers set activation_email_sent_at=now()"
                        " where id=%s and activation_email_claimed_at is not null"
                        "   and activation_email_sent_at is null", (rid,))
        chk("T12 a completed notification cannot be re-confirmed", cur.rowcount == 0,
            cur.rowcount)

        # ── a REPLACEMENT gets its own lifecycle ─────────────────────────
        c.execute("update tenant_phone_numbers set status='released', released_at=now()"
                  " where id=%s", (rid,))
        rep = str(uuid.uuid4())
        c.execute("insert into tenant_phone_numbers (id, tenant_id, e164, purpose,"
                  " status, provider, provider_account_sid, provider_sid, iso_country)"
                  " values (%s,%s,'+35315550999','permanent','provisioning','twilio',"
                  "%s,'PNreplace','IE')", (rep, tid, SUB))
        state = c.execute("select activation_email_sent_at is not null from"
                          " tenant_phone_numbers where id=%s", (rep,)).fetchone()[0]
        chk("T13 the replacement starts un-notified", state is False, state)
        cur = c.execute(CLAIM, (rep,))
        chk("T14 the replacement can be claimed independently", cur.rowcount == 1,
            cur.rowcount)
        old = c.execute("select activation_email_provider_id from tenant_phone_numbers"
                        " where id=%s", (rid,)).fetchone()[0]
        chk("T15 the original's notification record is untouched",
            old == "resend_ok", old)

        c.execute("delete from tenants where business_name like 'W9IGT%'")

    print(f"\n  STAGE T: {sum(ok)}/{len(ok)} passed" +
          ("  ALL PASS" if all(ok) else "  FAILURES"))
    return all(ok)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker()
    else:
        sys.exit(0 if parent() else 1)
