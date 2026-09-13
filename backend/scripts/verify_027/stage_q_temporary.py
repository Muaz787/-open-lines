"""W9I-E Stage A/U — does 027 already support a live temporary alongside a live
permanent? Measured, not assumed.

The whole gate turns on this. If the schema cannot hold both, a tenant under
regulatory review cannot have a working test line and their permanent one at the
same time, and W9I-E needs a migration before it can start.

Run as:
    stage_q_temporary.py parent
    stage_q_temporary.py worker <tenant> <e164> <start> <label> <out>
"""
import json, os, subprocess, sys, time, uuid
import psycopg

DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55433/w9e_scratch")
TMP = os.environ.get("W9IE_TMP", "/tmp")

INSERT = """
insert into tenant_phone_numbers
  (id, tenant_id, e164, purpose, status, provider, provider_account_sid,
   provider_sid, iso_country)
values (%s,%s,%s,%s,%s,'twilio',%s,%s,%s)
"""


def worker():
    tenant, e164, start, label, out = sys.argv[2:7]
    with psycopg.connect(DSN, autocommit=True) as c:
        while time.time() < float(start):
            pass
        res = {"label": label, "won": None, "sqlstate": None}
        try:
            c.execute(INSERT, (str(uuid.uuid4()), tenant, e164, "temporary_test",
                               "provisioning", "ACsub", f"PN{uuid.uuid4().hex}", "GB"))
            res["won"] = True
        except psycopg.Error as e:
            res["won"] = False
            res["sqlstate"] = e.sqlstate
            res["constraint"] = getattr(getattr(e, "diag", None), "constraint_name", None)
        json.dump(res, open(out, "w"))
        print(f"[{label}] {json.dumps(res)}")


def parent():
    ok = []
    def chk(l, cond, d=""):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {l}{'  ' + str(d) if d else ''}")

    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("delete from tenants where business_name like 'W9IE%'")
        tid = str(uuid.uuid4())
        c.execute("insert into tenants (id, business_name, industry, business_country_code)"
                  " values (%s,'W9IE temp','realtor','IE')", (tid,))

        def add(e164, purpose, status, iso="IE", sid=None, tenant=None):
            rid = str(uuid.uuid4())
            c.execute(INSERT, (rid, tenant or tid, e164, purpose, status, "ACsub",
                               sid or f"PN{uuid.uuid4().hex}", iso))
            return rid

        # ── the question this gate turns on ──────────────────────────────
        perm = add("+35312345678", "permanent", "active")
        try:
            temp = add("+442012345678", "temporary_test", "active", iso="GB")
            chk("Q1 a live temporary coexists with a live permanent", True)
        except psycopg.Error as e:
            chk("Q1 a live temporary coexists with a live permanent", False,
                f"{e.sqlstate} {getattr(e.diag,'constraint_name',None)}")
            temp = None

        # ── but only ONE of each ─────────────────────────────────────────
        for purpose, index in (("permanent", "tpn_one_current_permanent"),
                               ("temporary_test", "tpn_one_live_temporary")):
            try:
                add("+35399999999" if purpose == "permanent" else "+442099999999",
                    purpose, "active", iso="IE" if purpose == "permanent" else "GB")
                chk(f"Q2 a second live {purpose} is refused", False, "insert succeeded")
            except psycopg.Error as e:
                chk(f"Q2 a second live {purpose} is refused",
                    e.sqlstate == "23505"
                    and getattr(e.diag, "constraint_name", None) == index,
                    getattr(e.diag, "constraint_name", None))

        # ── the temporary rule is STRICTER: retiring still counts ────────
        c.execute("update tenant_phone_numbers set status='retiring' where id=%s", (temp,))
        try:
            add("+442099999999", "temporary_test", "provisioning", iso="GB")
            chk("Q3 a retiring temporary still blocks a second one", False,
                "insert succeeded")
        except psycopg.Error as e:
            chk("Q3 a retiring temporary still blocks a second one",
                getattr(e.diag, "constraint_name", None) == "tpn_one_live_temporary",
                getattr(e.diag, "constraint_name", None))
        # ...whereas a RETIRING permanent does not, because replacing a permanent
        # number requires the old one to keep ringing while the new one warms up.
        c.execute("update tenant_phone_numbers set status='retiring' where id=%s", (perm,))
        try:
            add("+35399999999", "permanent", "provisioning")
            chk("Q4 a retiring permanent DOES allow its replacement", True)
        except psycopg.Error as e:
            chk("Q4 a retiring permanent DOES allow its replacement", False,
                getattr(e.diag, "constraint_name", None))

        # ── released frees the temporary slot ────────────────────────────
        c.execute("update tenant_phone_numbers set status='released', released_at=now()"
                  " where id=%s", (temp,))
        try:
            temp2 = add("+442077777777", "temporary_test", "provisioning", iso="GB")
            chk("Q5 a released temporary frees the slot for a new one", True)
        except psycopg.Error as e:
            chk("Q5 a released temporary frees the slot for a new one", False,
                getattr(e.diag, "constraint_name", None))

        # ── routing: both live numbers resolve, unambiguously ────────────
        c.execute("delete from tenant_phone_numbers where tenant_id=%s", (tid,))
        add("+35312345678", "permanent", "active")
        add("+442012345678", "temporary_test", "active", iso="GB")
        rows = c.execute(
            "select e164, purpose from tenant_phone_numbers where tenant_id=%s"
            " and status in ('active','retiring') order by purpose", (tid,)).fetchall()
        chk("Q6 both live numbers are routable for one tenant", len(rows) == 2, rows)
        for e164 in ("+35312345678", "+442012345678"):
            n = c.execute("select count(distinct tenant_id) from tenant_phone_numbers"
                          " where e164=%s and status in ('active','retiring')",
                          (e164,)).fetchone()[0]
            chk(f"Q7 {e164} resolves to exactly one tenant", n == 1, n)

        # ── a temporary cannot squat an E.164 another tenant holds ───────
        other = str(uuid.uuid4())
        c.execute("insert into tenants (id, business_name, industry)"
                  " values (%s,'W9IE other','realtor')", (other,))
        try:
            add("+442012345678", "temporary_test", "provisioning", iso="GB", tenant=other)
            chk("Q8 a temporary cannot take an E.164 another tenant holds", False,
                "insert succeeded")
        except psycopg.Error as e:
            chk("Q8 a temporary cannot take an E.164 another tenant holds",
                getattr(e.diag, "constraint_name", None) == "tpn_owned_e164_key",
                getattr(e.diag, "constraint_name", None))

        # ── a live number must name the provider object it IS ────────────
        try:
            c.execute(
                "insert into tenant_phone_numbers (id, tenant_id, e164, purpose,"
                " status, provider, iso_country) values (%s,%s,'+442066666666',"
                "'temporary_test','active','twilio','GB')", (str(uuid.uuid4()), other))
            chk("Q9 an active temporary must carry provider identity", False,
                "insert succeeded")
        except psycopg.Error as e:
            chk("Q9 an active temporary must carry provider identity",
                getattr(e.diag, "constraint_name", None) == "tpn_live_identity_chk",
                getattr(e.diag, "constraint_name", None))

        # ── fixture for the race: one tenant, four workers, one slot ─────
        c.execute("delete from tenant_phone_numbers where tenant_id=%s", (tid,))

    start = time.time() + 2.0
    outs, procs = [], []
    for i in range(4):
        out = f"{TMP}/w9ie_race_{i}.json"
        outs.append(out)
        # Each worker tries a DIFFERENT number, as four concurrent acquisitions
        # would: the contention is over the tenant's one temporary slot, not over
        # an E.164.
        procs.append(subprocess.Popen(
            [sys.executable, __file__, "worker", tid, f"+44201234567{i}",
             str(start), f"w{i}", out]))
    for p in procs:
        p.wait()
    res = [json.load(open(o)) for o in outs]
    winners = [r for r in res if r["won"]]
    chk("Q10 four concurrent temporary acquisitions yield exactly one row",
        len(winners) == 1, [r["won"] for r in res])
    chk("Q11 every loser sees tpn_one_live_temporary, not a crash",
        all(r["sqlstate"] == "23505" and r["constraint"] == "tpn_one_live_temporary"
            for r in res if not r["won"]),
        [(r["sqlstate"], r.get("constraint")) for r in res if not r["won"]])

    with psycopg.connect(DSN, autocommit=True) as c:
        n = c.execute("select count(*) from tenant_phone_numbers where tenant_id=%s"
                      " and purpose='temporary_test'", (tid,)).fetchone()[0]
        chk("Q12 exactly one temporary row exists after the race", n == 1, n)
        c.execute("delete from tenants where business_name like 'W9IE%'")

    print(f"\n  STAGE Q: {sum(ok)}/{len(ok)} passed" +
          ("  ALL PASS" if all(ok) else "  FAILURES"))
    return all(ok)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker()
    else:
        sys.exit(0 if parent() else 1)
