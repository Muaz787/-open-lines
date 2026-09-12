"""W9H.1A Stage J — real INSERT/UPDATE proofs of migration 029.

Same discipline as stage_d.py: every refusal asserts the SQLSTATE AND the
constraint that fired, so a rejection by the wrong rule cannot pass for the right
one. 029 is NOT APPLIED to production; this proves what it would do.
"""
import os, uuid
import psycopg

DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55434/w9e_scratch")
FP_A = "a" * 64
FP_B = "b" * 64
results = []


def ok(n, label, q, args=(), *, conn):
    try:
        with conn.transaction():
            conn.execute(q, args)
        results.append((n, "PASS", label, "accepted"))
    except Exception as e:
        results.append((n, "FAIL", label, f"unexpectedly REJECTED: {type(e).__name__} {e}"))


def reject(n, label, q, args=(), state=None, con=None, *, conn):
    try:
        with conn.transaction():
            conn.execute(q, args)
        results.append((n, "FAIL", label, "was ACCEPTED — constraint absent"))
    except psycopg.Error as e:
        st = e.sqlstate
        c = getattr(getattr(e, "diag", None), "constraint_name", None) or ""
        good = (state is None or st == state) and (con is None or con in c)
        results.append((n, "PASS" if good else "FAIL", label,
                        f"{st} {c or str(e).splitlines()[0][:60]}"))


AUTH = ("insert into tenant_regulatory_authorizations "
        "(id, tenant_id, iso_country, end_user_type, tenant_regulatory_address_id,"
        " authorized_details_fingerprint, authorized_by, authorization_method,"
        " authorized_at, authorized_address_city, authorized_address_postal_code) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")

with psycopg.connect(DSN, autocommit=True) as c:
    c.execute("delete from tenants where business_name in ('W9H1A A','W9H1A B')")
    A, B = str(uuid.uuid4()), str(uuid.uuid4())
    for t, n in ((A, "W9H1A A"), (B, "W9H1A B")):
        c.execute("insert into tenants (id, business_name, industry) values (%s,%s,'salon')", (t, n))
    LA, LB, LC = (str(uuid.uuid4()) for _ in range(3))
    for l, t, s in ((LA, A, "lim"), (LB, A, "cork"), (LC, B, "b-loc")):
        c.execute("insert into tenant_locations (id, tenant_id, slug, name) values (%s,%s,%s,%s)",
                  (l, t, s, s))
    ADDR = ("insert into tenant_regulatory_addresses (id, tenant_id, tenant_location_id,"
            " iso_country, provider_account_sid, address_sid, validated, city, postal_code)"
            " values (%s,%s,%s,'IE',%s,%s,true,%s,%s)")
    A_LIM, A_CORK, A_DUB, B_ADDR = (str(uuid.uuid4()) for _ in range(4))
    c.execute(ADDR, (A_LIM, A, LA, "ACa", "ADlim", "Limerick", "V94 HT0X"))
    c.execute(ADDR, (A_CORK, A, LB, "ACa", "ADcork", "Cork", "T12 XY34"))
    c.execute(ADDR, (A_DUB, A, None, "ACa", "ADdub", "Dublin", "D02 AF30"))
    c.execute(ADDR, (B_ADDR, B, LC, "ACb", "ADb", "Galway", "H91 AB12"))

    # ── 1-3 multi-location: the reason this table exists
    lim1, cork1, dub1 = (str(uuid.uuid4()) for _ in range(3))
    ok(1, "Limerick authorisation accepted", AUTH,
       (lim1, A, "IE", "business", A_LIM, FP_A, "Ann Murphy", "dashboard",
        "2026-09-01T10:00:00Z", "Limerick", "V94 HT0X"), conn=c)
    ok(2, "Cork authorisation coexists with Limerick", AUTH,
       (cork1, A, "IE", "business", A_CORK, FP_B, "Ann Murphy", "email",
        "2026-09-02T10:00:00Z", "Cork", "T12 XY34"), conn=c)
    ok(3, "Dublin (tenant-level address) coexists with both", AUTH,
       (dub1, A, "IE", "business", A_DUB, "c" * 64, "Ann Murphy", "phone",
        "2026-09-03T10:00:00Z", "Dublin", "D02 AF30"), conn=c)
    n = c.execute("select count(*) from tenant_regulatory_authorizations "
                  "where tenant_id=%s and authorization_revoked_at is null", (A,)).fetchone()[0]
    results.append((4, "PASS" if n == 3 else "FAIL",
                    "three simultaneous ACTIVE authorisations", f"count={n}"))

    # ── 5-7 idempotency and history
    reject(5, "an identical ACTIVE authorisation is refused (idempotency)", AUTH,
           (str(uuid.uuid4()), A, "IE", "business", A_LIM, FP_A, "Ann Murphy",
            "dashboard", "2026-09-04T10:00:00Z", "Limerick", "V94 HT0X"),
           "23505", "tra_auth_active_key", conn=c)
    ok(6, "a DIFFERENT fact set for the same address is allowed (re-authorisation)",
       AUTH, (str(uuid.uuid4()), A, "IE", "business", A_LIM, "d" * 64, "Ann Murphy",
              "dashboard", "2026-09-05T10:00:00Z", "Limerick", "V94 HT0X"), conn=c)
    ok(7, "revoking v1 leaves it in the table", "update tenant_regulatory_authorizations "
       "set authorization_revoked_at=%s where id=%s", ("2026-09-06T10:00:00Z", lim1), conn=c)
    row = c.execute("select authorized_at, authorized_by, authorization_revoked_at "
                    "from tenant_regulatory_authorizations where id=%s", (lim1,)).fetchone()
    results.append((8, "PASS" if row and row[0] and row[1] == "Ann Murphy" and row[2] else "FAIL",
                    "a revoked authorisation keeps authorized_at and authorized_by",
                    str(row)))
    ok(9, "the SAME facts can be re-authorised once v1 is revoked", AUTH,
       (str(uuid.uuid4()), A, "IE", "business", A_LIM, FP_A, "Brendan O'Neill",
        "phone", "2026-09-07T10:00:00Z", "Limerick", "V94 HT0X"), conn=c)
    n = c.execute("select count(*) from tenant_regulatory_authorizations "
                  "where tenant_regulatory_address_id=%s", (A_LIM,)).fetchone()[0]
    results.append((10, "PASS" if n == 3 else "FAIL",
                    "history preserved for that address (v1 revoked + 2 active)", f"count={n}"))

    # ── 11-16 field discipline
    reject(11, "an invented authorisation method is refused", AUTH,
           (str(uuid.uuid4()), A, "IE", "business", B_ADDR, "e" * 64, "X", "sms",
            "2026-09-01T10:00:00Z", "Galway", None),
           "23514", "tra_auth_method_chk", conn=c)
    reject(12, "a non-sha256 fingerprint is refused", AUTH,
           (str(uuid.uuid4()), A, "IE", "business", A_DUB, "yes", "X", "email",
            "2026-09-01T10:00:00Z", "Dublin", None),
           "23514", "tra_auth_fingerprint_chk", conn=c)
    reject(13, "an UPPERCASE digest is refused (one canonical form)", AUTH,
           (str(uuid.uuid4()), A, "IE", "business", A_DUB, "A" * 64, "X", "email",
            "2026-09-01T10:00:00Z", "Dublin", None),
           "23514", "tra_auth_fingerprint_chk", conn=c)
    reject(14, "an authorisation attributed to nobody is refused", AUTH,
           (str(uuid.uuid4()), A, "IE", "business", A_DUB, "f" * 64, "   ", "email",
            "2026-09-01T10:00:00Z", "Dublin", None),
           "23514", "tra_auth_by_chk", conn=c)
    reject(15, "lowercase iso_country is refused", AUTH,
           (str(uuid.uuid4()), A, "ie", "business", A_DUB, "f" * 64, "X", "email",
            "2026-09-01T10:00:00Z", "Dublin", None),
           "23514", "tra_auth_iso_chk", conn=c)
    reject(16, "a revocation predating the authorisation is refused",
           "update tenant_regulatory_authorizations set authorization_revoked_at=%s "
           "where id=%s", ("2026-01-01T00:00:00Z", cork1),
           "23514", "tra_auth_revoked_after_chk", conn=c)

    # ── 17-19 cross-tenant, structurally
    reject(17, "tenant A cannot authorise tenant B's address", AUTH,
           (str(uuid.uuid4()), A, "IE", "business", B_ADDR, "f" * 64, "X", "email",
            "2026-09-01T10:00:00Z", "Galway", None),
           "23503", "tra_auth_address_owner_fk", conn=c)
    reject(18, "an authorisation naming no address is refused", AUTH,
           (str(uuid.uuid4()), A, "IE", "business", None, "f" * 64, "X", "email",
            "2026-09-01T10:00:00Z", "Dublin", None),
           "23502", None, conn=c)

    PROF = ("insert into tenant_regulatory_profiles (id, tenant_id, regulatory_address_id,"
            " iso_country, number_type, end_user_type, provider_account_sid, bundle_sid,"
            " state, requirements_fingerprint, authorization_id) "
            "values (%s,%s,%s,'IE','local','business',%s,%s,%s,repeat('a',64),%s)")
    reject(19, "tenant B's profile cannot cite tenant A's authorisation", PROF,
           (str(uuid.uuid4()), B, B_ADDR, "ACb", "BUb", "approved", cork1),
           "23503", "trp_authorization_owner_fk", conn=c)

    # ── 20-22 the filing must name its authorisation
    reject(20, "a SUBMITTED profile with no authorisation is refused", PROF,
           (str(uuid.uuid4()), A, A_CORK, "ACa", "BUx", "pending_review", None),
           "23514", "trp_submitted_authorization_chk", conn=c)
    ok(21, "a DRAFT profile with no authorisation is allowed", PROF,
       (str(uuid.uuid4()), A, A_CORK, "ACa", None, "details_required", None), conn=c)
    ok(22, "a submitted profile citing its authorisation is accepted", PROF,
       (str(uuid.uuid4()), A, A_DUB, "ACa", "BUy", "approved", cork1), conn=c)

    # ── 23-25 deletion behaviour
    # A_LIM is cited ONLY by authorisations -- A_CORK and A_DUB also carry profiles,
    # and Postgres would report 027's profile FK first, which proves the wrong thing.
    reject(23, "an address a live authorisation cites cannot be deleted",
           "delete from tenant_regulatory_addresses where id=%s", (A_LIM,),
           "23503", "tra_auth_address_owner_fk", conn=c)
    ok(24, "deleting the TENANT cascades everything in one statement",
       "delete from tenants where id=%s", (A,), conn=c)
    left = c.execute("select count(*) from tenant_regulatory_authorizations "
                     "where tenant_id=%s", (A,)).fetchone()[0]
    results.append((25, "PASS" if left == 0 else "FAIL",
                    "authorisations cascaded with the tenant", f"remaining={left}"))
    c.execute("delete from tenants where id=%s", (B,))

bad = [r for r in results if r[1] != "PASS"]
for n, s, label, detail in sorted(results):
    print(f"  [{s}] {n:>2}. {label}\n        {detail}")
print(f"\n{len(results) - len(bad)}/{len(results)} passed"
      + ("" if not bad else f" — {len(bad)} FAILED"))
print("ALL PASS" if not bad else "FAILURES PRESENT")
