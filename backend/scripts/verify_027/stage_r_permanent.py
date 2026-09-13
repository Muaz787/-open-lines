"""W9I-F Stage J/K/S — the transitional state, against real PostgreSQL.

The gate's expected end state is unusual and worth proving rather than assuming:

    temporary_test = active      (taking the customer's calls)
    permanent      = provisioning (bought, wired, NOT routable)

Both on one tenant, at the same time. If 027 cannot hold that, W9I-F needs a
migration before it can do anything. It can.

Run as:
    stage_r_permanent.py parent
    stage_r_permanent.py worker <tenant> <e164> <start> <label> <out>
"""
import json, os, subprocess, sys, time, uuid
import psycopg

DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55433/w9e_scratch")
TMP = os.environ.get("W9IF_TMP", "/tmp")

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
            c.execute(INSERT, (str(uuid.uuid4()), tenant, e164, "permanent",
                               "provisioning", "ACsub", f"PN{uuid.uuid4().hex}", "IE"))
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
        c.execute("delete from tenants where business_name like 'W9IF%'")
        tid = str(uuid.uuid4())
        c.execute("insert into tenants (id, business_name, industry, business_country_code)"
                  " values (%s,'W9IF perm','realtor','IE')", (tid,))

        def add(e164, purpose, status, iso, tenant=None, sid=None):
            rid = str(uuid.uuid4())
            c.execute(INSERT, (rid, tenant or tid, e164, purpose, status, "ACsub",
                               sid or f"PN{uuid.uuid4().hex}", iso))
            return rid

        # ── THE TRANSITIONAL STATE ───────────────────────────────────────
        temp = add("+442071234567", "temporary_test", "active", "GB")
        try:
            perm = add("+35315550123", "permanent", "provisioning", "IE")
            chk("R1 an ACTIVE temporary and a PROVISIONING permanent coexist", True)
        except psycopg.Error as e:
            chk("R1 an ACTIVE temporary and a PROVISIONING permanent coexist", False,
                getattr(e.diag, "constraint_name", None))
            perm = None

        # ── ONLY THE TEMPORARY IS ROUTABLE ───────────────────────────────
        routable = c.execute(
            "select e164, purpose from tenant_phone_numbers where tenant_id=%s"
            " and status in ('active','retiring')", (tid,)).fetchall()
        chk("R2 exactly one routable number, and it is the temporary",
            routable == [("+442071234567", "temporary_test")], routable)
        n = c.execute("select count(*) from tenant_phone_numbers where e164=%s"
                      " and status in ('active','retiring')",
                      ("+35315550123",)).fetchone()[0]
        chk("R3 the provisioning permanent resolves for no inbound call", n == 0, n)

        # ── a second permanent is still refused ──────────────────────────
        try:
            add("+35315550999", "permanent", "provisioning", "IE")
            chk("R4 a second live permanent is refused", False, "insert succeeded")
        except psycopg.Error as e:
            chk("R4 a second live permanent is refused",
                getattr(e.diag, "constraint_name", None) == "tpn_one_current_permanent",
                getattr(e.diag, "constraint_name", None))

        # ── promotion (W9I-G's job) is a legal move from here ────────────
        c.execute("update tenant_phone_numbers set status='active' where id=%s", (perm,))
        both = c.execute(
            "select purpose from tenant_phone_numbers where tenant_id=%s"
            " and status='active' order by purpose", (tid,)).fetchall()
        chk("R5 after promotion both numbers may ring during the grace window",
            both == [("permanent",), ("temporary_test",)], both)
        # ...and the temporary can then be retired without touching the permanent.
        c.execute("update tenant_phone_numbers set status='retiring',"
                  " retiring_since=now() where id=%s", (temp,))
        c.execute("update tenant_phone_numbers set status='released',"
                  " released_at=now() where id=%s", (temp,))
        left = c.execute(
            "select e164 from tenant_phone_numbers where tenant_id=%s"
            " and status in ('active','retiring')", (tid,)).fetchall()
        chk("R6 retiring the temporary leaves the permanent live", 
            left == [("+35315550123",)], left)

        # ── cross-tenant safety ──────────────────────────────────────────
        other = str(uuid.uuid4())
        c.execute("insert into tenants (id, business_name, industry)"
                  " values (%s,'W9IF other','realtor')", (other,))
        try:
            add("+35315550123", "permanent", "provisioning", "IE", tenant=other)
            chk("R7 another tenant cannot claim this +353", False, "insert succeeded")
        except psycopg.Error as e:
            chk("R7 another tenant cannot claim this +353",
                getattr(e.diag, "constraint_name", None) == "tpn_owned_e164_key",
                getattr(e.diag, "constraint_name", None))

        # ── a live permanent must carry its provider identity ────────────
        try:
            c.execute(
                "insert into tenant_phone_numbers (id, tenant_id, e164, purpose,"
                " status, provider, iso_country) values (%s,%s,'+35315550777',"
                "'permanent','active','twilio','IE')", (str(uuid.uuid4()), other))
            chk("R8 an active permanent must name its provider object", False,
                "insert succeeded")
        except psycopg.Error as e:
            chk("R8 an active permanent must name its provider object",
                getattr(e.diag, "constraint_name", None) == "tpn_live_identity_chk",
                getattr(e.diag, "constraint_name", None))

        # fixture for the race: one tenant, one permanent slot
        c.execute("delete from tenant_phone_numbers where tenant_id=%s", (tid,))
        add("+442071234567", "temporary_test", "active", "GB")

    start = time.time() + 2.0
    outs, procs = [], []
    for i in range(4):
        out = f"{TMP}/w9if_race_{i}.json"
        outs.append(out)
        procs.append(subprocess.Popen(
            [sys.executable, __file__, "worker", tid, f"+3531555012{i}",
             str(start), f"w{i}", out]))
    for p in procs:
        p.wait()
    res = [json.load(open(o)) for o in outs]
    winners = [r for r in res if r["won"]]
    chk("R9 four concurrent acquisitions record exactly one permanent",
        len(winners) == 1, [r["won"] for r in res])
    chk("R10 every loser sees tpn_one_current_permanent",
        all(r["sqlstate"] == "23505" and r["constraint"] == "tpn_one_current_permanent"
            for r in res if not r["won"]),
        [(r["sqlstate"], r.get("constraint")) for r in res if not r["won"]])

    with psycopg.connect(DSN, autocommit=True) as c:
        n = c.execute("select count(*) from tenant_phone_numbers where tenant_id=%s"
                      " and purpose='permanent'", (tid,)).fetchone()[0]
        chk("R11 exactly one permanent row exists after the race", n == 1, n)
        t = c.execute("select count(*) from tenant_phone_numbers where tenant_id=%s"
                      " and purpose='temporary_test' and status='active'",
                      (tid,)).fetchone()[0]
        chk("R12 the temporary number was untouched by the race", t == 1, t)
        c.execute("delete from tenants where business_name like 'W9IF%'")

    print(f"\n  STAGE R: {sum(ok)}/{len(ok)} passed" +
          ("  ALL PASS" if all(ok) else "  FAILURES"))
    return all(ok)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker()
    else:
        sys.exit(0 if parent() else 1)
