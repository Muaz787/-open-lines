"""W9I-C Stage Q — the authorisation model under real PostgreSQL.

The router suite proves the DECISIONS. What it cannot prove is that the database
agrees: that the partial unique index really does make a duplicate authorisation
idempotent rather than a second row, that history really is immutable under
concurrent consent, and that two premises really are independently authorisable.

Those are properties of 029's schema, and only Postgres can answer for them.

Run as:
    stage_p_authorization_api.py parent
    stage_p_authorization_api.py worker <tenant> <address> <fp> <start> <label> <out>
"""
import json, os, subprocess, sys, time, uuid
import psycopg

DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55433/w9e_scratch")
TMP = os.environ.get("W9IC_TMP", "/tmp")

INSERT = """
insert into tenant_regulatory_authorizations
  (id, tenant_id, iso_country, end_user_type, tenant_regulatory_address_id,
   authorized_details_fingerprint, authorized_by, authorization_method,
   authorized_at, authorized_address_city)
values (%s,%s,'IE','business',%s,%s,%s,'dashboard',now(),'Limerick')
"""


def worker():
    tenant, address, fp, start, label, out = sys.argv[2:8]
    with psycopg.connect(DSN, autocommit=True) as c:
        while time.time() < float(start):
            pass
        res = {"label": label, "won": None, "sqlstate": None}
        try:
            c.execute(INSERT, (str(uuid.uuid4()), tenant, address, fp,
                               f"{label}@example.ie"))
            res["won"] = True
        except psycopg.Error as e:
            res["won"] = False
            res["sqlstate"] = e.sqlstate
            res["constraint"] = getattr(getattr(e, "diag", None), "constraint_name", None)
        json.dump(res, open(out, "w"))
        print(f"[{label}] {json.dumps(res)}")


def parent():
    sys.path.insert(0, "/Users/muazmuhamed/open-lines/backend")
    from services import regulatory_authorization as auth

    ok = []
    def chk(l, cond, d=""):
        ok.append(bool(cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {l}{'  ' + str(d) if d else ''}")

    DETAILS = {"business_name": "Example Trading Limited",
               "business_registration_number": "123456",
               "business_website": "https://example.ie",
               "authorized_rep_first_name": "Aoife",
               "authorized_rep_last_name": "Ni Bhriain",
               "authorized_rep_email": "aoife@example.ie"}
    LIMERICK = {"street": "20 Thomas Street", "street_secondary": None,
                "city": "Limerick", "region": "Limerick",
                "postal_code": "V94 HT0X", "iso_country": "IE"}
    CORK = {**LIMERICK, "city": "Cork", "region": "Cork", "postal_code": "T12 ABCD"}

    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("delete from tenants where business_name like 'W9IC%'")
        tid = str(uuid.uuid4())
        c.execute("insert into tenants (id, business_name, industry, business_country_code)"
                  " values (%s,'W9IC verify','realtor','IE')", (tid,))

        # A SECOND Irish premises needs a tenant_location_id. tra_tenant_scope_key
        # allows exactly one country-level address per tenant (where the location
        # is NULL); tra_location_scope_key then allows one more per location. That
        # is the multi-location model 027 built, and it is why the API must never
        # grow a tenant-level "the address" shortcut -- DANI has several premises.
        def add_location(name):
            lid = str(uuid.uuid4())
            c.execute("insert into tenant_locations (id, tenant_id, slug, name, aliases)"
                      " values (%s,%s,%s,%s,'{}')", (lid, tid, name.lower(), name))
            return lid

        def add_address(a, location_id=None):
            aid = str(uuid.uuid4())
            c.execute(
                "insert into tenant_regulatory_addresses (id, tenant_id, iso_country,"
                " tenant_location_id, street, street_secondary, city, region,"
                " postal_code, validated, address_sid, provider_account_sid)"
                " values (%s,%s,'IE',%s,%s,%s,%s,%s,%s,true,%s,'ACqa')",
                (aid, tid, location_id, a["street"], a["street_secondary"], a["city"],
                 a["region"], a["postal_code"], f"AD{uuid.uuid4().hex}"))
            return aid

        lim = add_address(LIMERICK)
        cork = add_address(CORK, add_location("Cork"))
        fp_lim = auth.fingerprint_for(DETAILS, {**LIMERICK, "id": lim})
        fp_cork = auth.fingerprint_for(DETAILS, {**CORK, "id": cork})
        chk("P1 two premises produce different fingerprints", fp_lim != fp_cork)

        # ── one authorisation per exact scope+facts ──────────────────────
        c.execute(INSERT, (str(uuid.uuid4()), tid, lim, fp_lim, "owner@example.ie"))
        chk("P2 an authorisation is recorded", True)
        try:
            c.execute(INSERT, (str(uuid.uuid4()), tid, lim, fp_lim, "owner@example.ie"))
            chk("P3 an identical active authorisation is refused by the index", False,
                "second insert succeeded")
        except psycopg.Error as e:
            chk("P3 an identical active authorisation is refused by the index",
                e.sqlstate == "23505"
                and getattr(e.diag, "constraint_name", None) == "tra_auth_active_key",
                getattr(e.diag, "constraint_name", None))

        # ── independent premises ─────────────────────────────────────────
        c.execute(INSERT, (str(uuid.uuid4()), tid, cork, fp_cork, "owner@example.ie"))
        n = c.execute("select count(*) from tenant_regulatory_authorizations "
                      "where tenant_id=%s", (tid,)).fetchone()[0]
        chk("P4 a second premises is independently authorisable", n == 2, n)

        # ── an edited fact needs a new authorisation, and history survives ─
        edited = {**DETAILS, "business_website": "https://new.example.ie"}
        fp_edit = auth.fingerprint_for(edited, {**LIMERICK, "id": lim})
        chk("P5 editing a fact changes the fingerprint", fp_edit != fp_lim)
        live = c.execute(
            "select count(*) from tenant_regulatory_authorizations where tenant_id=%s"
            " and tenant_regulatory_address_id=%s and authorized_details_fingerprint=%s"
            " and authorization_revoked_at is null", (tid, lim, fp_edit)).fetchone()[0]
        chk("P6 the edited facts have no live authorisation", live == 0, live)
        c.execute(INSERT, (str(uuid.uuid4()), tid, lim, fp_edit, "owner@example.ie"))
        rows = c.execute(
            "select authorized_details_fingerprint from tenant_regulatory_authorizations"
            " where tenant_id=%s and tenant_regulatory_address_id=%s order by authorized_at",
            (tid, lim)).fetchall()
        chk("P7 the original authorisation is still on file, unchanged",
            [r[0] for r in rows] == [fp_lim, fp_edit], len(rows))

        # ── restoring the fact revives the original ──────────────────────
        restored = auth.fingerprint_for(DETAILS, {**LIMERICK, "id": lim})
        chk("P8 restoring the value reproduces the original fingerprint",
            restored == fp_lim)

        # ── revocation ───────────────────────────────────────────────────
        c.execute("update tenant_regulatory_authorizations set authorization_revoked_at=now()"
                  " where tenant_id=%s and tenant_regulatory_address_id=%s"
                  " and authorized_details_fingerprint=%s", (tid, lim, fp_lim))
        live = c.execute(
            "select count(*) from tenant_regulatory_authorizations where tenant_id=%s"
            " and tenant_regulatory_address_id=%s and authorized_details_fingerprint=%s"
            " and authorization_revoked_at is null", (tid, lim, fp_lim)).fetchone()[0]
        chk("P9 a revoked authorisation is no longer live", live == 0, live)
        # and the same facts may be authorised again afterwards -- consent renewed,
        # not resurrected.
        c.execute(INSERT, (str(uuid.uuid4()), tid, lim, fp_lim, "owner@example.ie"))
        chk("P10 the same facts can be authorised again after revocation", True)
        total = c.execute("select count(*) from tenant_regulatory_authorizations"
                          " where tenant_id=%s", (tid,)).fetchone()[0]
        chk("P11 every authorisation ever given is still on file", total == 4, total)

        # ── cross-tenant ─────────────────────────────────────────────────
        other = str(uuid.uuid4())
        c.execute("insert into tenants (id, business_name, industry)"
                  " values (%s,'W9IC other','realtor')", (other,))
        try:
            c.execute(INSERT, (str(uuid.uuid4()), other, lim, fp_lim, "x@example.ie"))
            chk("P12 another tenant cannot authorise this tenant's address", False,
                "insert succeeded")
        except psycopg.Error as e:
            chk("P12 another tenant cannot authorise this tenant's address",
                e.sqlstate == "23503", getattr(e.diag, "constraint_name", None))

        # ── fixture for the race ─────────────────────────────────────────
        race_addr = add_address({**LIMERICK, "city": "Galway", "postal_code": "H91 ABCD"},
                                add_location("Galway"))
        fp_race = auth.fingerprint_for(DETAILS, {**LIMERICK, "city": "Galway",
                                                 "postal_code": "H91 ABCD", "id": race_addr})

    start = time.time() + 2.0
    outs, procs = [], []
    for i in range(4):
        out = f"{TMP}/w9ic_race_{i}.json"
        outs.append(out)
        procs.append(subprocess.Popen(
            [sys.executable, __file__, "worker", tid, race_addr, fp_race,
             str(start), f"w{i}", out]))
    for p in procs:
        p.wait()
    res = [json.load(open(o)) for o in outs]
    winners = [r for r in res if r["won"]]
    chk("P13 four concurrent consents produce exactly one authorisation",
        len(winners) == 1, [r["won"] for r in res])
    chk("P14 every loser sees the uniqueness invariant, not a crash",
        all(r["sqlstate"] == "23505" and r["constraint"] == "tra_auth_active_key"
            for r in res if not r["won"]),
        [(r["sqlstate"], r.get("constraint")) for r in res if not r["won"]])

    with psycopg.connect(DSN, autocommit=True) as c:
        n = c.execute("select count(*) from tenant_regulatory_authorizations"
                      " where tenant_regulatory_address_id=%s", (race_addr,)).fetchone()[0]
        chk("P15 exactly one row exists for the raced scope", n == 1, n)
        # Gate 1: nothing in this gate creates a provider identity.
        for table, label in (("tenant_regulatory_profiles", "profiles"),
                             ("tenant_regulatory_provider_claims", "provider claims"),
                             ("tenant_phone_numbers", "phone numbers")):
            n = c.execute(f"select count(*) from {table} where tenant_id=%s",
                          (tid,)).fetchone()[0]
            chk(f"P16 no {label} were created by authorising", n == 0, n)
        c.execute("delete from tenants where business_name like 'W9IC%'")

    print(f"\n  STAGE P: {sum(ok)}/{len(ok)} passed" +
          ("  ALL PASS" if all(ok) else "  FAILURES"))
    return all(ok)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker()
    else:
        sys.exit(0 if parent() else 1)
