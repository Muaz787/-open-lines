"""W9E Stage D — real INSERT/UPDATE proofs of every migration-027 constraint.

Each numbered proof issues an actual statement against PostgreSQL 15.19 and asserts
the outcome AND, for refusals, the SQLSTATE and the constraint that fired. A
refusal with the wrong SQLSTATE would mean something other than the intended
invariant rejected the row.
"""
import psycopg, uuid, os
DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55432/w9e_scratch")
A = str(uuid.uuid4()); B = str(uuid.uuid4())
LA1 = str(uuid.uuid4()); LA2 = str(uuid.uuid4()); LB1 = str(uuid.uuid4())
results = []

def _sql(cur, q, args=()):
    cur.execute(q, args)

def expect_ok(n, label, q, args=(), *, conn):
    with conn.transaction() as _:
        try:
            conn.execute(q, args)
            results.append((n, "PASS", label, "accepted"))
        except Exception as e:
            results.append((n, "FAIL", label, f"unexpectedly REJECTED: {type(e).__name__} {e}"))
            raise psycopg.Rollback

def expect_reject(n, label, q, args=(), want_state=None, want_con=None, *, conn):
    try:
        with conn.transaction():
            conn.execute(q, args)
        results.append((n, "FAIL", label, "was ACCEPTED — constraint absent"))
        return
    except psycopg.Rollback:
        return
    except psycopg.Error as e:
        st = e.sqlstate
        con = getattr(getattr(e, "diag", None), "constraint_name", None) or ""
        good = (want_state is None or st == want_state) and (want_con is None or want_con in con)
        results.append((n, "PASS" if good else "FAIL", label,
                        f"{st} {con or (str(e).splitlines()[0][:60])}"))

TENANT = "insert into tenants (id, business_name, industry) values (%s, %s, 'salon')"
LOC = ("insert into tenant_locations (id, tenant_id, slug, name) values (%s,%s,%s,%s)")
ADDR = ("insert into tenant_regulatory_addresses "
        "(id, tenant_id, tenant_location_id, iso_country, provider_account_sid, address_sid,"
        " supporting_document_sid, validated, provider_locality) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s)")
PROF = ("insert into tenant_regulatory_profiles "
        "(id, tenant_id, regulatory_address_id, iso_country, number_type, end_user_type,"
        " provider_account_sid, bundle_sid, state) values (%s,%s,%s,%s,%s,%s,%s,%s,%s)")
PHONE = ("insert into tenant_phone_numbers "
         "(id, tenant_id, tenant_location_id, regulatory_profile_id, e164, purpose, status,"
         " provider_account_sid, provider_sid, iso_country) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")
EVENT = ("insert into tenant_regulatory_events "
         "(id, bundle_sid, bundle_status, fingerprint, occurrence, tenant_id,"
         " regulatory_profile_id, signature_valid) values (%s,%s,%s,%s,%s,%s,%s,%s)")
FP = "a" * 64

with psycopg.connect(DSN, autocommit=True) as c:
    # Re-runnable: clear anything a previous run of THIS script left behind. The
    # fixtures use fixed provider SIDs on purpose (they make the failure messages
    # readable), so without this a second run collides with its own first run.
    c.execute("delete from tenants where business_name in ('W9E Tenant A','W9E Tenant B')")
    c.execute("delete from tenant_regulatory_events where bundle_sid in "
              "('BU_unknown','BU_x') or tenant_id is null")
    # ── fixtures: two tenants, two locations for A (both "Dublin"), one for B
    c.execute(TENANT, (A, "W9E Tenant A"))
    c.execute(TENANT, (B, "W9E Tenant B"))
    c.execute(LOC, (LA1, A, "dublin-main", "Dublin Main"))
    c.execute(LOC, (LA2, A, "dublin-second", "Dublin Second"))
    c.execute(LOC, (LB1, B, "cork", "Cork"))

    # ── 1-3 business country
    expect_ok(1, "business_country_code='IE' accepted",
              "update tenants set business_country_code='IE' where id=%s", (A,), conn=c)
    expect_reject(2, "lowercase 'ie' rejected",
                  "update tenants set business_country_code='ie' where id=%s", (A,),
                  "23514", "tenants_business_country_code_chk", conn=c)
    expect_reject(3, "'IRL' rejected (3 letters)",
                  "update tenants set business_country_code='IRL' where id=%s", (A,),
                  "23514", "tenants_business_country_code_chk", conn=c)
    expect_ok(3.1, "NULL business_country_code allowed (legacy tenants)",
              "update tenants set business_country_code=null where id=%s", (B,), conn=c)

    # ── real addresses/profiles for A and B
    AA1 = str(uuid.uuid4()); AA2 = str(uuid.uuid4()); AB1 = str(uuid.uuid4())
    c.execute(ADDR, (AA1, A, LA1, "IE", "ACa", "ADa1", "RDa1", True, "Dublin 8"))
    # 9) second address, SAME locality text, DIFFERENT location -> must coexist
    expect_ok(9, "two addresses in the same locality for different locations coexist",
              ADDR, (AA2, A, LA2, "IE", "ACa", "ADa2", "RDa2", True, "Dublin 8"), conn=c)
    c.execute(ADDR, (AB1, B, LB1, "IE", "ACb", "ADb1", "RDb1", True, "Cork"))

    # ── 4 cross-tenant address reference
    expect_reject(4, "profile of A referencing an address of B rejected",
                  PROF, (str(uuid.uuid4()), A, AB1, "IE", "local", "business", "ACa",
                         "BUx1", "pending_review"),
                  "23503", "trp_address_owner_fk", conn=c)

    PA_DUB = str(uuid.uuid4()); PA_CORK = str(uuid.uuid4()); PA_WIDE = str(uuid.uuid4())
    c.execute(PROF, (PA_DUB, A, AA1, "IE", "local", "business", "ACa", "BU_dub", "approved"))
    # 12) Dublin + a second address-scoped profile coexist
    expect_ok(12, "address-scoped profiles for two different addresses coexist",
              PROF, (PA_CORK, A, AA2, "IE", "local", "business", "ACa", "BU_sec", "approved"),
              conn=c)
    # 11) duplicate address-scoped profile (same address, same country/type) rejected
    expect_reject(11, "duplicate address-scoped profile rejected",
                  PROF, (str(uuid.uuid4()), A, AA1, "IE", "local", "business", "ACa",
                         "BU_dup", "approved"),
                  "23505", "trp_address_scope_key", conn=c)
    # 10) country-wide profile (address NULL) - one allowed, second rejected
    expect_ok(10.1, "country-wide profile (address NULL) accepted",
              PROF, (PA_WIDE, A, None, "IE", "mobile", "business", "ACa", "BU_wide",
                     "approved"), conn=c)
    expect_reject(10, "duplicate country-wide profile rejected",
                  PROF, (str(uuid.uuid4()), A, None, "IE", "mobile", "business", "ACa",
                         "BU_wide2", "approved"),
                  "23505", "trp_country_scope_key", conn=c)
    # 13) duplicate bundle sid
    expect_reject(13, "duplicate Bundle SID rejected (callback routing integrity)",
                  PROF, (str(uuid.uuid4()), B, None, "IE", "local", "business", "ACb",
                         "BU_dub", "approved"),
                  "23505", "trp_bundle_sid_key", conn=c)

    # ── 5-6 phone ownership
    expect_reject(5, "phone of A referencing a location of B rejected",
                  PHONE, (str(uuid.uuid4()), A, LB1, None, "+353161700001", "permanent",
                          "active", "ACa", "PN1", "IE"),
                  "23503", "tpn_location_owner_fk", conn=c)
    PB_WIDE = str(uuid.uuid4())
    c.execute(PROF, (PB_WIDE, B, None, "IE", "local", "business", "ACb", "BU_b", "approved"))
    expect_reject(6, "phone of A referencing a profile of B rejected",
                  PHONE, (str(uuid.uuid4()), A, None, PB_WIDE, "+353161700002", "permanent",
                          "active", "ACa", "PN2", "IE"),
                  "23503", "tpn_profile_owner_fk", conn=c)

    # ── 7-8 event ownership
    expect_reject(7, "event claiming tenant A while referencing B's profile rejected",
                  EVENT, (str(uuid.uuid4()), "BU_b", "pending-review", FP, 1, A, PB_WIDE, True),
                  "23503", "tre_profile_owner_fk", conn=c)
    expect_reject(8, "event with a profile but NULL tenant_id rejected",
                  EVENT, (str(uuid.uuid4()), "BU_b", "pending-review", FP, 1, None,
                          PB_WIDE, True),
                  "23514", "tre_profile_needs_tenant_chk", conn=c)
    expect_ok(8.1, "unresolved event (both NULL) accepted",
              EVENT, (str(uuid.uuid4()), "BU_unknown", "pending-review", "b"*64, 1,
                      None, None, False), conn=c)

    # ── 14-19 phone lifecycle
    P1 = str(uuid.uuid4())
    c.execute(PHONE, (P1, A, LA1, PA_DUB, "+353161700010", "permanent", "active",
                      "ACa", "PN10", "IE"))
    expect_reject(14, "second ACTIVE permanent rejected",
                  PHONE, (str(uuid.uuid4()), A, None, None, "+353161700011", "permanent",
                          "active", "ACa", "PN11", "IE"),
                  "23505", "tpn_one_current_permanent", conn=c)
    expect_reject(15, "second PROVISIONING permanent rejected (no double purchase)",
                  PHONE, (str(uuid.uuid4()), A, None, None, "+353161700012", "permanent",
                          "provisioning", "ACa", None, "IE"),
                  "23505", "tpn_one_current_permanent", conn=c)
    c.execute("update tenant_phone_numbers set status='retiring', retiring_since=now() "
              "where id=%s", (P1,))
    expect_ok(16, "retiring permanent + NEW active permanent allowed (replacement)",
              PHONE, (str(uuid.uuid4()), A, None, None, "+353161700013", "permanent",
                      "active", "ACa", "PN13", "IE"), conn=c)

    T1 = str(uuid.uuid4())
    c.execute(PHONE, (T1, A, None, None, "+447400000001", "temporary_test", "active",
                      "ACa", "PNt1", "GB"))
    expect_reject(17, "second temporary while the first is ACTIVE rejected",
                  PHONE, (str(uuid.uuid4()), A, None, None, "+447400000002",
                          "temporary_test", "active", "ACa", "PNt2", "GB"),
                  "23505", "tpn_one_live_temporary", conn=c)
    c.execute("update tenant_phone_numbers set status='retiring' where id=%s", (T1,))
    expect_reject(18, "second temporary while the first is RETIRING rejected (abuse guard)",
                  PHONE, (str(uuid.uuid4()), A, None, None, "+447400000003",
                          "temporary_test", "active", "ACa", "PNt3", "GB"),
                  "23505", "tpn_one_live_temporary", conn=c)
    c.execute("update tenant_phone_numbers set status='released', released_at=now() "
              "where id=%s", (T1,))
    expect_ok(19, "released temporary permits a future temporary",
              PHONE, (str(uuid.uuid4()), A, None, None, "+447400000004", "temporary_test",
                      "active", "ACa", "PNt4", "GB"), conn=c)

    # ── 20-21 E.164
    expect_reject(20, "duplicate routable E.164 across tenants rejected",
                  PHONE, (str(uuid.uuid4()), B, None, None, "+353161700013", "permanent",
                          "active", "ACb", "PNb13", "IE"),
                  "23505", "tpn_owned_e164_key", conn=c)
    c.execute("update tenant_phone_numbers set status='released', released_at=now() "
              "where e164=%s", ("+353161700013",))
    expect_ok(21, "released E.164 can legitimately be taken again (by another tenant)",
              PHONE, (str(uuid.uuid4()), B, None, None, "+353161700013", "permanent",
                      "active", "ACb", "PNb13", "IE"), conn=c)

    # ── 22 provider object identity
    expect_reject(22, "duplicate provider object (account + PN sid) rejected",
                  PHONE, (str(uuid.uuid4()), B, None, None, "+353161700099", "temporary_test",
                          "active", "ACb", "PNb13", "IE"),
                  "23505", "tpn_provider_object_key", conn=c)

    # ── 23-26 live provider identity
    expect_reject(23, "ACTIVE phone without provider_sid rejected",
                  PHONE, (str(uuid.uuid4()), B, None, None, "+353161700020", "temporary_test",
                          "active", "ACb", None, "IE"),
                  "23514", "tpn_live_identity_chk", conn=c)
    expect_reject(24, "ACTIVE phone without provider_account_sid rejected",
                  PHONE, (str(uuid.uuid4()), B, None, None, "+353161700021", "temporary_test",
                          "active", None, "PNz1", "IE"),
                  "23514", "tpn_live_identity_chk", conn=c)
    expect_reject(25, "RETIRING phone without provider identity rejected",
                  PHONE, (str(uuid.uuid4()), B, None, None, "+353161700022", "temporary_test",
                          "retiring", None, None, "IE"),
                  "23514", "tpn_live_identity_chk", conn=c)
    expect_ok(26, "PROVISIONING phone with no provider identity yet accepted",
              PHONE, (str(uuid.uuid4()), B, None, None, "+353161700023", "temporary_test",
                      "provisioning", None, None, "IE"), conn=c)
    expect_reject("26b", "activated_at_source='tenant_created_at' rejected",
                  "update tenant_phone_numbers set activated_at=now(), "
                  "activated_at_source='tenant_created_at' where id=%s", (P1,),
                  "23514", "tpn_activated_source_chk", conn=c)
    expect_ok("26c", "activated_at_source='provider_date_created' accepted",
              "update tenant_phone_numbers set activated_at=now(), "
              "activated_at_source='provider_date_created' where id=%s", (P1,), conn=c)
    expect_reject("26d", "bad E.164 shape rejected",
                  PHONE, (str(uuid.uuid4()), B, None, None, "0871234567", "temporary_test",
                          "provisioning", None, None, "IE"),
                  "23514", "tpn_e164_chk", conn=c)

    # ── 27 validated address provider identity
    expect_reject(27, "validated address without an address_sid rejected",
                  ADDR, (str(uuid.uuid4()), B, None, "IE", "ACb", None, None, True, "Cork"),
                  "23514", "tra_validated_identity_chk", conn=c)
    expect_ok("27b", "UNVALIDATED draft address with no SIDs accepted",
              ADDR, (str(uuid.uuid4()), B, None, "IE", None, None, None, False, None),
              conn=c)
    expect_reject("27c", "second tenant-level address for one country rejected",
                  ADDR, (str(uuid.uuid4()), B, None, "IE", None, None, None, False, None),
                  "23505", "tra_tenant_scope_key", conn=c)
    # Isolated deliberately: B already has an address at LB1, so reusing LB1 would
    # trip tra_location_scope_key first and prove nothing about SID uniqueness. A
    # SECOND location for B keeps the location key satisfied so the SID key is the
    # only thing left that can refuse the row.
    LB2 = str(uuid.uuid4())
    c.execute(LOC, (LB2, B, "cork-second", "Cork Second"))
    expect_reject("27d", "duplicate Twilio Address SID within one account rejected",
                  ADDR, (str(uuid.uuid4()), B, LB2, "IE", "ACb", "ADb1", "RDzz", True, "Cork"),
                  "23505", "tra_address_sid_key", conn=c)
    expect_ok("27e", "a DIFFERENT address SID at that second location is accepted",
              ADDR, (str(uuid.uuid4()), B, LB2, "IE", "ACb", "ADb2", "RDb2", True, "Cork"),
              conn=c)
    expect_reject("27f", "duplicate SupportingDocument SID within one account rejected",
                  ADDR, (str(uuid.uuid4()), A, LA1, "GB", "ACa", "ADnew", "RDa1", True, "London"),
                  "23505", "tra_document_sid_key", conn=c)

    # ── 28 submitted profile provider identity
    expect_reject(28, "submitted profile (pending_review) without a bundle_sid rejected",
                  PROF, (str(uuid.uuid4()), B, None, "IE", "toll-free", "business", "ACb",
                         None, "pending_review"),
                  "23514", "trp_submitted_identity_chk", conn=c)
    expect_ok("28b", "DRAFT profile (details_required) without a bundle_sid accepted",
              PROF, (str(uuid.uuid4()), B, None, "IE", "toll-free", "business", None,
                     None, "details_required"), conn=c)
    expect_reject("28c", "bundle_sid without provider_account_sid rejected",
                  PROF, (str(uuid.uuid4()), B, None, "IE", "national", "business", None,
                         "BU_noacct", "approved"),
                  "23514", "trp_bundle_account_chk", conn=c)
    expect_reject("28d", "'provisionally_approved' is not one of our states",
                  PROF, (str(uuid.uuid4()), B, None, "IE", "national", "business", "ACb",
                         "BU_pa", "provisionally_approved"),
                  "23514", "trp_state_chk", conn=c)
    expect_ok("28e", "bundle_status may hold Twilio's provisionally-approved verbatim",
              PROF, (str(uuid.uuid4()), B, None, "IE", "national", "business", "ACb",
                     "BU_pa2", "pending_review"), conn=c)
    c.execute("update tenant_regulatory_profiles set bundle_status='provisionally-approved' "
              "where bundle_sid='BU_pa2'")
    st = c.execute("select bundle_status, state from tenant_regulatory_profiles "
                   "where bundle_sid='BU_pa2'").fetchone()
    results.append(("28f", "PASS" if st == ("provisionally-approved", "pending_review") else "FAIL",
                    "provider status stored verbatim while our state stays pending_review", str(st)))

    # ── fingerprint shape
    expect_reject("G1", "non-sha256 fingerprint rejected",
                  EVENT, (str(uuid.uuid4()), "BU_x", "draft", "nothex", 1, None, None, True),
                  "23514", "tre_fingerprint_chk", conn=c)
    expect_reject("G2", "duplicate (bundle, fingerprint, occurrence) rejected",
                  EVENT, (str(uuid.uuid4()), "BU_unknown", "pending-review", "b"*64, 1,
                          None, None, False),
                  "23505", "tre_fingerprint_occurrence_key", conn=c)
    expect_ok("G3", "same bundle + same fingerprint at occurrence 2 accepted (recurrence)",
              EVENT, (str(uuid.uuid4()), "BU_unknown", "pending-review", "b"*64, 2,
                      None, None, False), conn=c)

for n, verdict, label, detail in results:
    print(f"  [{verdict}] {str(n):>4}  {label}")
    if detail:
        print(f"                 {detail}")
bad = [r for r in results if r[1] == "FAIL"]
print(f"\n  STAGE D: {len(results)-len(bad)}/{len(results)} proofs passed"
      f"{'' if not bad else '  — FAILURES: ' + str([r[0] for r in bad])}")
