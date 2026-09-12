"""W9E Stage E — delete/cascade semantics, MEASURED against PostgreSQL 15.19.

Each scenario builds the minimum rows needed to isolate exactly one referential
decision, so a refusal can only have come from the FK under test.
"""
import psycopg, uuid, os
DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55432/w9e_scratch")
res = []
def rec(label, ok, detail=""): res.append((label, "PASS" if ok else "FAIL", detail))

def attempt(c, label, sql, args, *, expect_refusal):
    try:
        with c.transaction():
            c.execute(sql, args)
        rec(label, not expect_refusal, "ALLOWED")
        return True
    except psycopg.Error as e:
        rec(label, expect_refusal,
            f"REFUSED {e.sqlstate} {getattr(e.diag, 'constraint_name', '') or ''}")
        return False

n = [0]
def tag():
    n[0] += 1
    return f"e{n[0]:02d}"

with psycopg.connect(DSN, autocommit=True) as c:
    c.execute("delete from tenants where business_name = 'W9E cascade'")
    c.execute("delete from tenant_regulatory_events where tenant_id is null")
    def tenant():
        t = str(uuid.uuid4()); c.execute("insert into tenants (id, business_name, industry) values (%s, %s, 'salon')", (t, "W9E cascade")); return t
    def location(t, k):
        i = str(uuid.uuid4())
        c.execute("insert into tenant_locations (id,tenant_id,slug,name) values (%s,%s,%s,%s)",
                  (i, t, f"loc-{k}", f"Loc {k}")); return i
    def address(t, loc, k):
        i = str(uuid.uuid4())
        c.execute("insert into tenant_regulatory_addresses (id,tenant_id,tenant_location_id,"
                  "iso_country,provider_account_sid,address_sid,supporting_document_sid,validated)"
                  " values (%s,%s,%s,'IE',%s,%s,%s,true)", (i, t, loc, f"AC{k}", f"AD{k}", f"RD{k}"))
        return i
    def authorization(t, ad):
        """029's trp_submitted_authorization_chk requires a submitted profile to
        name its authorisation; these fixtures are 'approved'. Not under test here
        -- stage_j.py proves the authorisation constraints."""
        i = str(uuid.uuid4())
        c.execute("insert into tenant_regulatory_authorizations (id,tenant_id,iso_country,"
                  "end_user_type,tenant_regulatory_address_id,authorized_details_fingerprint,"
                  "authorized_by,authorization_method,authorized_at,authorized_address_city) "
                  "values (%s,%s,'IE','business',%s,repeat('a',64),'A Representative',"
                  "'dashboard',now(),'Dublin')", (i, t, ad))
        return i

    def profile(t, ad, k, loc=None):
        i = str(uuid.uuid4())
        # requirements_fingerprint: 028's trp_submitted_requirements_chk, for the
        # same reason.
        c.execute("insert into tenant_regulatory_profiles (id,tenant_id,tenant_location_id,"
                  "regulatory_address_id,iso_country,provider_account_sid,bundle_sid,state,"
                  "requirements_fingerprint,authorization_id) "
                  "values (%s,%s,%s,%s,'IE',%s,%s,'approved',repeat('a',64),%s)",
                  (i, t, loc, ad, f"AC{k}", f"BU{k}", authorization(t, ad)))
        return i
    def phone(t, k, loc=None, prof=None):
        i = str(uuid.uuid4())
        c.execute("insert into tenant_phone_numbers (id,tenant_id,tenant_location_id,"
                  "regulatory_profile_id,e164,purpose,status,provider_account_sid,provider_sid,"
                  "iso_country) values (%s,%s,%s,%s,%s,'permanent','active',%s,%s,'IE')",
                  (i, t, loc, prof, f"+35316{n[0]:02d}70{n[0]:04d}", f"AC{k}", f"PN{k}"))
        return i
    def event(t, prof, bundle, k):
        i = str(uuid.uuid4())
        c.execute("insert into tenant_regulatory_events (id,bundle_sid,bundle_status,fingerprint,"
                  "occurrence,tenant_id,regulatory_profile_id,signature_valid) "
                  "values (%s,%s,'twilio-approved',%s,1,%s,%s,true)",
                  (i, bundle, f"{k}".ljust(64, 'f')[:64].replace('e','a'), t, prof))
        return i

    # ── A: a location referenced ONLY by a regulatory address
    k = tag(); t = tenant(); L = location(t, k); address(t, L, k)
    attempt(c, "A. delete a tenant_location referenced by a regulatory address",
            "delete from tenant_locations where id=%s", (L,), expect_refusal=True)

    # ── B: a location referenced ONLY by a phone row
    k = tag(); t = tenant(); L = location(t, k); phone(t, k, loc=L)
    attempt(c, "B. delete a tenant_location referenced by a phone row",
            "delete from tenant_locations where id=%s", (L,), expect_refusal=True)

    # ── B2: an unreferenced location deletes cleanly (the control)
    k = tag(); t = tenant(); L2 = location(t, k)
    attempt(c, "B2. delete an UNREFERENCED tenant_location (control)",
            "delete from tenant_locations where id=%s", (L2,), expect_refusal=False)

    # ── A2: an address referenced by a profile
    k = tag(); t = tenant(); L = location(t, k); AD = address(t, L, k); profile(t, AD, k)
    attempt(c, "A2. delete a regulatory address referenced by a profile",
            "delete from tenant_regulatory_addresses where id=%s", (AD,), expect_refusal=True)

    # ── D: a profile referenced ONLY by an event  -> ON DELETE SET NULL
    k = tag(); t = tenant(); L = location(t, k); AD = address(t, L, k)
    PR = profile(t, AD, k); EV = event(t, PR, f"BU{k}", k)
    before = c.execute("select tenant_id, regulatory_profile_id from tenant_regulatory_events "
                       "where id=%s", (EV,)).fetchone()
    if attempt(c, "D. delete a regulatory profile referenced by an event",
               "delete from tenant_regulatory_profiles where id=%s", (PR,), expect_refusal=False):
        after = c.execute("select tenant_id, regulatory_profile_id from tenant_regulatory_events "
                          "where id=%s", (EV,)).fetchone()
        rows = c.execute("select count(*) from tenant_regulatory_events where id=%s",
                         (EV,)).fetchone()[0]
        rec("D2. the event is DELETED with its profile (CASCADE, not a half-nulled row)",
            rows == 0 and after is None,
            f"before=(tenant,profile)={before}  after={after}  event_rows={rows}")

    # ── E: a profile referenced by a PHONE (NO ACTION -> refuse)
    k = tag(); t = tenant(); L = location(t, k); AD = address(t, L, k)
    PR = profile(t, AD, k); phone(t, k, loc=L, prof=PR)
    attempt(c, "E. delete a regulatory profile referenced by a phone row",
            "delete from tenant_regulatory_profiles where id=%s", (PR,), expect_refusal=True)

    # ── C: delete a tenant owning ALL FIVE kinds of row
    k = tag(); t = tenant(); L = location(t, k); AD = address(t, L, k)
    PR = profile(t, AD, k, loc=L); PH = phone(t, k, loc=L, prof=PR)
    EV = event(t, PR, f"BU{k}", k)
    tables = ("tenant_locations", "tenant_regulatory_addresses",
              "tenant_regulatory_profiles", "tenant_phone_numbers")
    before = {tb: c.execute(f"select count(*) from {tb} where tenant_id=%s", (t,)).fetchone()[0]
              for tb in tables}
    before["tenant_regulatory_events"] = c.execute(
        "select count(*) from tenant_regulatory_events where tenant_id=%s", (t,)).fetchone()[0]
    if attempt(c, "C. delete a tenant owning locations, addresses, profiles, phones and events",
               "delete from tenants where id=%s", (t,), expect_refusal=False):
        after = {tb: c.execute(f"select count(*) from {tb} where tenant_id=%s", (t,)).fetchone()[0]
                 for tb in tables}
        ev = c.execute("select tenant_id, regulatory_profile_id, bundle_sid, bundle_status "
                       "from tenant_regulatory_events where id=%s", (EV,)).fetchone()
        rec("C2. every owned row is gone", all(v == 0 for v in after.values()),
            f"before={before} after={after}")
        rec("C3. the tenant's events go WITH the tenant (no retained FailureReason "
            "about a deleted customer)", ev is None,
            f"event row after tenant delete: {ev}")

for label, verdict, detail in res:
    print(f"  [{verdict}] {label}")
    print(f"          {detail}")
bad = [r for r in res if r[1] == "FAIL"]
print(f"\n  STAGE E: {len(res)-len(bad)}/{len(res)} passed"
      f"{'' if not bad else ' — FAILURES: ' + str([r[0] for r in bad])}")
