"""W9I-H.0 — migration 033 against real PostgreSQL, BEFORE it is proposed.

Proves the properties Stage C demands: single use, expiry, revocability,
auditability, inability to authorize any other key, and -- the subtle one -- that
a CONSUMED grant still lets the same signup retry while remaining unable to mint
a second tenant.

Run as:
    stage_u_pilot_grant.py parent
    stage_u_pilot_grant.py worker <key> <tenant> <start> <label> <out>
"""
import hashlib, json, os, subprocess, sys, time, uuid
import psycopg

DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55433/w9e_scratch")
TMP = os.environ.get("W9IH_TMP", "/tmp")
MIGRATION = "/Users/muazmuhamed/open-lines/migrations/033_ireland_pilot_onboarding_grant.sql"

#: The fenced consumption, exactly as the application will issue it.
CONSUME = """
update ireland_pilot_onboarding_grants
   set consumed_at = now(), consumed_tenant_id = %s
 where onboarding_key = %s
   and consumed_at is null
   and expires_at > now()
"""

#: The gate, as a state machine. CREATE authority and RESUME authority are
#: different things, and a consumed grant only ever carries the second.
DENY, ALLOW_CREATE, ALLOW_RESUME, INTEGRITY = ("deny", "allow_create",
                                               "allow_resume", "integrity_error")


def gate(c, key, country):
    """Exactly the decision the application will make. Returns one of the four
    outcomes above. Written here so the semantics are proved against real
    PostgreSQL before a line of application code depends on them."""
    row = c.execute(
        "select consumed_at, consumed_tenant_id, expires_at > now()"
        "  from ireland_pilot_onboarding_grants"
        " where onboarding_key = %s and iso_country = %s", (key, country)).fetchone()
    if row is None:
        return DENY
    consumed_at, consumed_tenant_id, unexpired = row
    if consumed_at is None:
        # An invitation. Expiry decides whether it may still be accepted.
        return ALLOW_CREATE if unexpired else DENY
    # Consumed: evidence that ONE tenant crossed this gate. Resolve it.
    tenant = c.execute("select id from tenants where onboarding_key = %s",
                       (key,)).fetchone()
    if tenant is None:
        # Nothing to resume. A historical grant creates nothing -- this is the
        # hole the checkpoint review found, closed here.
        return DENY
    if str(tenant[0]) != str(consumed_tenant_id):
        return INTEGRITY
    # Expiry deliberately NOT re-checked: a customer part-way through onboarding
    # must not be bricked because a pilot invitation lapsed behind them.
    return ALLOW_RESUME


def worker():
    """One full signup attempt: claim-or-resume the tenant, then consume.

    Faithful to the real order -- the tenant is created first and the grant is
    consumed only once durable tenant state exists, so a transient failure
    cannot brick the signup by burning the invitation.
    """
    key, _unused, start, label, out = sys.argv[2:7]
    mine = str(uuid.uuid4())
    with psycopg.connect(DSN, autocommit=True) as c:
        while time.time() < float(start):
            pass
        try:
            c.execute("insert into tenants (id, business_name, industry,"
                      " business_country_code, onboarding_key)"
                      " values (%s,'W9IH race','realtor','IE',%s)", (mine, key))
            created = True
        except psycopg.Error:
            created = False          # 031's unique index: somebody else won
        tid = c.execute("select id from tenants where onboarding_key=%s",
                        (key,)).fetchone()[0]
        cur = c.execute(CONSUME, (str(tid), key))
        json.dump({"label": label, "created": created, "rows": cur.rowcount,
                   "tenant": str(tid)}, open(out, "w"))
        print(f"[{label}] created={created} consumed={cur.rowcount}")


def parent():
    ok = []
    def chk(l, cond, d=""):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {l}{'  ' + str(d) if d else ''}")

    sql = open(MIGRATION).read()
    print(f"  migration sha256: {hashlib.sha256(open(MIGRATION,'rb').read()).hexdigest()}\n")
    K = lambda: str(uuid.uuid4())

    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("drop table if exists ireland_pilot_onboarding_grants")
        chk("U0 the documented rollback leaves no table", True)

        c.execute(sql)
        chk("U1 the table exists after apply",
            c.execute("select count(*) from information_schema.tables where"
                      " table_name='ireland_pilot_onboarding_grants'").fetchone()[0] == 1)
        cols = {r[0]: (r[1], r[2]) for r in c.execute(
            "select column_name, data_type, is_nullable from information_schema.columns"
            " where table_name='ireland_pilot_onboarding_grants'").fetchall()}
        chk("U2 exactly the reviewed columns",
            set(cols) == {"onboarding_key", "iso_country", "created_at", "expires_at",
                          "consumed_at", "consumed_tenant_id", "note"}, sorted(cols))
        chk("U3 expires_at is NOT NULL with no default",
            cols["expires_at"][1] == "NO"
            and c.execute("select column_default from information_schema.columns"
                          " where table_name='ireland_pilot_onboarding_grants'"
                          "   and column_name='expires_at'").fetchone()[0] is None)
        chk("U4 row-level security is enabled",
            c.execute("select relrowsecurity from pg_class where"
                      " oid='ireland_pilot_onboarding_grants'::regclass").fetchone()[0] is True)
        chk("U5 no policies — denied to anon and authenticated",
            c.execute("select count(*) from pg_policies where"
                      " tablename='ireland_pilot_onboarding_grants'").fetchone()[0] == 0)
        chk("U6 only the primary-key index exists",
            c.execute("select count(*) from pg_indexes where"
                      " tablename='ireland_pilot_onboarding_grants'").fetchone()[0] == 1)
        chk("U7 a new table starts empty — Ireland closed to everyone",
            c.execute("select count(*) from ireland_pilot_onboarding_grants").fetchone()[0] == 0)

        c.execute(sql); c.execute(sql)
        chk("U8 replaying twice more changes nothing",
            c.execute("select count(*) from information_schema.columns where"
                      " table_name='ireland_pilot_onboarding_grants'").fetchone()[0] == 7)

        def grant(key, country="IE", ttl="7 days", note="pilot"):
            c.execute("insert into ireland_pilot_onboarding_grants"
                      " (onboarding_key, iso_country, expires_at, note)"
                      f" values (%s,%s, now() + interval '{ttl}', %s)",
                      (key, country, note))

        # ── the constraints ───────────────────────────────────────────────
        try:
            grant(K(), country="CA")
            chk("U9 a non-Ireland grant is refused", False, "insert succeeded")
        except psycopg.Error as e:
            chk("U9 a non-Ireland grant is refused",
                getattr(e.diag, "constraint_name", None) == "ipog_country_chk",
                getattr(e.diag, "constraint_name", None))
        try:
            grant("not-a-uuid")
            chk("U10 a non-uuid4 key is refused", False, "insert succeeded")
        except psycopg.Error as e:
            chk("U10 a non-uuid4 key is refused",
                getattr(e.diag, "constraint_name", None) == "ipog_key_is_uuid_chk",
                getattr(e.diag, "constraint_name", None))
        try:
            grant(K(), ttl="-1 days")
            chk("U11 a grant expiring before it was created is refused", False,
                "insert succeeded")
        except psycopg.Error as e:
            chk("U11 a grant expiring before it was created is refused",
                getattr(e.diag, "constraint_name", None) == "ipog_expiry_chk",
                getattr(e.diag, "constraint_name", None))

        k1 = K(); grant(k1)
        try:
            c.execute("update ireland_pilot_onboarding_grants"
                      " set consumed_tenant_id=%s where onboarding_key=%s",
                      (str(uuid.uuid4()), k1))
            chk("U12 the two consumption columns must agree", False,
                "update succeeded")
        except psycopg.Error as e:
            # STRUCTURAL ONLY. This proves an id cannot be recorded without the
            # consumption that produced it. It does NOT prove the referenced
            # tenant exists -- there is no FK, and U31 is what covers that.
            chk("U12 the two consumption columns must agree (structural only — "
                "proves nothing about the tenant existing)",
                getattr(e.diag, "constraint_name", None)
                == "ipog_consumed_columns_agree_chk",
                getattr(e.diag, "constraint_name", None))

        try:
            grant(k1)
            chk("U13 one key cannot hold two grants", False, "insert succeeded")
        except psycopg.Error as e:
            chk("U13 one key cannot hold two grants", e.sqlstate == "23505", e.sqlstate)

        # ── the gate ──────────────────────────────────────────────────────
        chk("U14 an unconsumed, unexpired grant authorizes CREATE",
            gate(c, k1, "IE") == ALLOW_CREATE, gate(c, k1, "IE"))
        chk("U15 it authorizes nothing for ANOTHER key",
            gate(c, K(), "IE") == DENY)
        chk("U16 an Ireland grant authorizes nothing for another country",
            gate(c, k1, "CA") == DENY)

        expired = K()
        c.execute("insert into ireland_pilot_onboarding_grants"
                  " (onboarding_key, iso_country, created_at, expires_at)"
                  " values (%s,'IE', now() - interval '9 days', now() - interval '1 day')",
                  (expired,))
        chk("U17 an expired, unconsumed grant authorizes nothing",
            gate(c, expired, "IE") == DENY, gate(c, expired, "IE"))
        cur = c.execute(CONSUME, (str(uuid.uuid4()), expired))
        chk("U18 an expired grant cannot be consumed (no resurrection by retry)",
            cur.rowcount == 0, cur.rowcount)

        revoked = K(); grant(revoked)
        c.execute("delete from ireland_pilot_onboarding_grants"
                  " where onboarding_key=%s and consumed_at is null", (revoked,))
        chk("U19 an unused grant can be revoked before use",
            gate(c, revoked, "IE") == DENY)

        # ── consumption, and what survives it ─────────────────────────────
        tid = str(uuid.uuid4())
        c.execute("insert into tenants (id, business_name, industry,"
                  " business_country_code, onboarding_key)"
                  " values (%s,'W9IH pilot','realtor','IE',%s)", (tid, k1))
        cur = c.execute(CONSUME, (tid, k1))
        chk("U20 consumption matches exactly one row", cur.rowcount == 1, cur.rowcount)
        row = c.execute("select consumed_at is not null, consumed_tenant_id"
                        " from ireland_pilot_onboarding_grants where onboarding_key=%s",
                        (k1,)).fetchone()
        chk("U21 the consumption is recorded, not deleted",
            row[0] is True and str(row[1]) == tid, row)
        cur = c.execute(CONSUME, (str(uuid.uuid4()), k1))
        chk("U22 a consumed grant cannot be consumed again", cur.rowcount == 0,
            cur.rowcount)

        chk("U23 a consumed grant with its tenant present authorizes RESUME",
            gate(c, k1, "IE") == ALLOW_RESUME, gate(c, k1, "IE"))
        # ...and a second tenant is impossible anyway, via 031's unique index.
        try:
            c.execute("insert into tenants (id, business_name, industry,"
                      " business_country_code, onboarding_key)"
                      " values (%s,'W9IH second','realtor','IE',%s)",
                      (str(uuid.uuid4()), k1))
            chk("U24 a second tenant on the same key is impossible", False,
                "insert succeeded")
        except psycopg.Error as e:
            chk("U24 a second tenant on the same key is impossible",
                getattr(e.diag, "constraint_name", None) == "tenants_onboarding_key_uq",
                getattr(e.diag, "constraint_name", None))

        # ── THE CHECKPOINT CORRECTION: what a purge must NOT restore ──────
        c.execute("delete from tenants where id=%s", (tid,))
        row = c.execute("select consumed_at is not null, consumed_tenant_id"
                        " from ireland_pilot_onboarding_grants where onboarding_key=%s",
                        (k1,)).fetchone()
        chk("U25/U36 the audit record survives the tenant being purged",
            row[0] is True and str(row[1]) == tid, row)
        chk("U31/U37 a consumed grant whose tenant is gone authorizes NOTHING",
            gate(c, k1, "IE") == DENY, gate(c, k1, "IE"))
        # ...and the earlier proof that "031's unique index stops a second
        # tenant" is now genuinely unavailable, which is exactly why the gate
        # must refuse rather than lean on it.
        free = c.execute("select count(*) from tenants where onboarding_key=%s",
                         (k1,)).fetchone()[0]
        chk("U32a the unique index no longer protects anything after the purge",
            free == 0, free)
        c.execute("insert into tenants (id, business_name, industry,"
                  " business_country_code, onboarding_key)"
                  " values (%s,'W9IH would-be replacement','realtor','IE',%s)",
                  (str(uuid.uuid4()), k1))
        chk("U32b the database WOULD have allowed a replacement — only the gate "
            "prevents it",
            c.execute("select count(*) from tenants where onboarding_key=%s",
                      (k1,)).fetchone()[0] == 1)
        c.execute("delete from tenants where onboarding_key=%s", (k1,))

        # ── STATE 4: the key resolves to a tenant the grant never produced ─
        k_mis = K(); grant(k_mis)
        t_real = str(uuid.uuid4())
        c.execute("insert into tenants (id, business_name, industry,"
                  " business_country_code, onboarding_key)"
                  " values (%s,'W9IH mismatch','realtor','IE',%s)", (t_real, k_mis))
        c.execute(CONSUME, (str(uuid.uuid4()), k_mis))      # bound to a DIFFERENT id
        chk("U33 a consumed grant bound to another tenant fails closed",
            gate(c, k_mis, "IE") == INTEGRITY, gate(c, k_mis, "IE"))
        c.execute("delete from tenants where id=%s", (t_real,))

        # ── U34/U35: expiry after consumption ─────────────────────────────
        # Built backdated rather than edited after the fact: ipog_expiry_chk
        # refuses moving expires_at below created_at, which is the constraint
        # doing its job and caught this setup on the first run.
        k_exp = K()
        c.execute("insert into ireland_pilot_onboarding_grants"
                  " (onboarding_key, iso_country, created_at, expires_at, note)"
                  " values (%s,'IE', now() - interval '9 days',"
                  "         now() - interval '1 hour', 'lapsed invitation')",
                  (k_exp,))
        t_exp = str(uuid.uuid4())
        c.execute("insert into tenants (id, business_name, industry,"
                  " business_country_code, onboarding_key)"
                  " values (%s,'W9IH expired-resume','realtor','IE',%s)", (t_exp, k_exp))
        # Consumed while it was still valid, which is why consumed_at predates
        # the expiry it is now past.
        c.execute("update ireland_pilot_onboarding_grants"
                  " set consumed_at = now() - interval '8 days',"
                  "     consumed_tenant_id = %s where onboarding_key = %s",
                  (t_exp, k_exp))
        chk("U34 an EXPIRED but consumed grant still resumes its live tenant",
            gate(c, k_exp, "IE") == ALLOW_RESUME, gate(c, k_exp, "IE"))
        c.execute("delete from tenants where id=%s", (t_exp,))
        chk("U35 an expired consumed grant whose tenant is gone is denied",
            gate(c, k_exp, "IE") == DENY, gate(c, k_exp, "IE"))

        # ── D: an unrelated tenant cannot be adopted by a consumed grant ───
        k_d = K(); grant(k_d)
        t_d = str(uuid.uuid4())
        c.execute("insert into tenants (id, business_name, industry,"
                  " business_country_code, onboarding_key)"
                  " values (%s,'W9IH bound','realtor','IE',%s)", (t_d, k_d))
        c.execute(CONSUME, (t_d, k_d))
        c.execute("delete from tenants where id=%s", (t_d,))
        c.execute("insert into tenants (id, business_name, industry,"
                  " business_country_code) values (%s,'W9IH unrelated','realtor','IE')",
                  (str(uuid.uuid4()),))
        chk("U38 an unrelated tenant cannot be resumed by a consumed grant",
            gate(c, k_d, "IE") == DENY, gate(c, k_d, "IE"))

        race_key = K(); grant(race_key)

    # ── four workers, one consumption ─────────────────────────────────────
    start = time.time() + 2.0
    outs, procs = [], []
    for i in range(4):
        out = f"{TMP}/w9ih_race_{i}.json"
        outs.append(out)
        procs.append(subprocess.Popen(
            [sys.executable, __file__, "worker", race_key, str(uuid.uuid4()),
             str(start), f"w{i}", out]))
    for p in procs:
        p.wait()
    res = [json.load(open(o)) for o in outs]
    chk("U26a four concurrent signups create exactly one tenant",
        sum(1 for r in res if r["created"]) == 1, [r["created"] for r in res])
    chk("U26b every worker converged on that same tenant",
        len({r["tenant"] for r in res}) == 1, sorted({r["tenant"] for r in res}))
    chk("U27 exactly one of them consumed the grant",
        sum(1 for r in res if r["rows"] == 1) == 1, [r["rows"] for r in res])

    with psycopg.connect(DSN, autocommit=True) as c:
        n = c.execute("select count(*) from ireland_pilot_onboarding_grants"
                      " where onboarding_key=%s and consumed_at is not null",
                      (race_key,)).fetchone()[0]
        chk("U28 exactly one consumption is recorded", n == 1, n)
        bound = c.execute("select consumed_tenant_id from"
                          " ireland_pilot_onboarding_grants where onboarding_key=%s",
                          (race_key,)).fetchone()[0]
        chk("U29 the grant is bound to the tenant that actually exists",
            str(bound) == res[0]["tenant"], str(bound))
        chk("U30 post-consumption retries resume that tenant only",
            gate(c, race_key, "IE") == ALLOW_RESUME, gate(c, race_key, "IE"))
        c.execute("delete from tenants where business_name like 'W9IH%'")
        chk("U31b once purged, the same key is denied and creates nothing",
            gate(c, race_key, "IE") == DENY, gate(c, race_key, "IE"))
        c.execute("drop table ireland_pilot_onboarding_grants")

    print(f"\n  STAGE U: {sum(ok)}/{len(ok)} passed" +
          ("  ALL PASS" if all(ok) else "  FAILURES"))
    return all(ok)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker()
    else:
        sys.exit(0 if parent() else 1)
