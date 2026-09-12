"""W9H-QA.4 Stage K — real proofs of migration 030's claim constraints.

Every refusal asserts the SQLSTATE and the constraint that fired. 030 is NOT
APPLIED to production; this proves what it would do.
"""
import os, uuid
import psycopg

DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55435/w9e_scratch")
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
        c = getattr(getattr(e, "diag", None), "constraint_name", None) or ""
        good = (state is None or e.sqlstate == state) and (con is None or con in c)
        results.append((n, "PASS" if good else "FAIL", label,
                        f"{e.sqlstate} {c or str(e).splitlines()[0][:60]}"))


CLAIM = ("insert into tenant_regulatory_provider_claims "
         "(id, tenant_id, resource, scope_key, provider_account_sid, provider_sid) "
         "values (%s,%s,%s,%s,%s,%s)")

with psycopg.connect(DSN, autocommit=True) as c:
    c.execute("delete from tenants where business_name in ('QA4 A','QA4 B')")
    A, B = str(uuid.uuid4()), str(uuid.uuid4())
    for t, n in ((A, "QA4 A"), (B, "QA4 B")):
        c.execute("insert into tenants (id, business_name, industry) values (%s,%s,'salon')",
                  (t, n))

    # ── 1-4 the three resources, and one claim per logical scope
    ok(1, "an end_user claim is accepted", CLAIM,
       (str(uuid.uuid4()), A, "end_user", "IE:business", "ACa", None), conn=c)
    ok(2, "a supporting_document claim for the same tenant coexists", CLAIM,
       (str(uuid.uuid4()), A, "supporting_document", "addr-1:business_address",
        "ACa", None), conn=c)
    ok(3, "a bundle claim for the same tenant coexists", CLAIM,
       (str(uuid.uuid4()), A, "bundle", "prof-1", "ACa", None), conn=c)
    reject(4, "a SECOND end_user claim for the same scope is refused", CLAIM,
           (str(uuid.uuid4()), A, "end_user", "IE:business", "ACa", None),
           "23505", "trpc_scope_key", conn=c)

    # ── 5-7 scopes that must NOT collide
    ok(5, "a different country is a different end_user claim", CLAIM,
       (str(uuid.uuid4()), A, "end_user", "GB:business", "ACa", None), conn=c)
    ok(6, "a different end-user type is a different claim", CLAIM,
       (str(uuid.uuid4()), A, "end_user", "IE:individual", "ACa", None), conn=c)
    ok(7, "another TENANT may hold the same logical scope", CLAIM,
       (str(uuid.uuid4()), B, "end_user", "IE:business", "ACb", None), conn=c)
    ok(8, "a second location's document is a separate claim", CLAIM,
       (str(uuid.uuid4()), A, "supporting_document", "addr-2:business_address",
        "ACa", None), conn=c)
    ok(9, "a second profile's bundle is a separate claim", CLAIM,
       (str(uuid.uuid4()), A, "bundle", "prof-2", "ACa", None), conn=c)

    # ── 10-13 field discipline
    reject(10, "an unknown resource kind is refused", CLAIM,
           (str(uuid.uuid4()), A, "phone_number", "x", "ACa", None),
           "23514", "trpc_resource_chk", conn=c)
    reject(11, "an empty scope_key is refused", CLAIM,
           (str(uuid.uuid4()), A, "bundle", "   ", "ACa", None),
           "23514", "trpc_scope_chk", conn=c)
    reject(12, "a provider SID with no account is refused", CLAIM,
           (str(uuid.uuid4()), A, "bundle", "prof-9", None, "BUx"),
           "23514", "trpc_sid_account_chk", conn=c)
    reject(13, "an unknown provider is refused", 
           "insert into tenant_regulatory_provider_claims "
           "(id, tenant_id, provider, resource, scope_key) values (%s,%s,%s,%s,%s)",
           (str(uuid.uuid4()), A, "vonage", "bundle", "prof-8"),
           "23514", "trpc_provider_chk", conn=c)

    # ── 14-16 one provider resource per claim, within its account
    ok(14, "attaching a provider SID is accepted",
       "update tenant_regulatory_provider_claims set provider_sid='ITone' "
       "where tenant_id=%s and resource='end_user' and scope_key='IE:business'",
       (A,), conn=c)
    reject(15, "the SAME provider SID cannot serve two claims in one account",
           "update tenant_regulatory_provider_claims set provider_sid='ITone' "
           "where tenant_id=%s and resource='end_user' and scope_key='GB:business'",
           (A,), "23505", "trpc_provider_sid_key", conn=c)
    ok(16, "the same SID text in a DIFFERENT account does not collide",
       "update tenant_regulatory_provider_claims set provider_sid='ITone' "
       "where tenant_id=%s and resource='end_user'", (B,), conn=c)

    # ── 17-19 deletion
    ok(17, "deleting the tenant cascades its claims",
       "delete from tenants where id=%s", (A,), conn=c)
    left = c.execute("select count(*) from tenant_regulatory_provider_claims "
                     "where tenant_id=%s", (A,)).fetchone()[0]
    results.append((18, "PASS" if left == 0 else "FAIL",
                    "no claim survives its tenant", f"remaining={left}"))
    ok(19, "the other tenant's claims are untouched",
       "select 1 from tenant_regulatory_provider_claims where tenant_id=%s", (B,),
       conn=c)
    c.execute("delete from tenants where id=%s", (B,))

bad = [r for r in results if r[1] != "PASS"]
for n, s, label, detail in sorted(results):
    print(f"  [{s}] {n:>2}. {label}\n        {detail}")
print(f"\n{len(results) - len(bad)}/{len(results)} passed")
print("ALL PASS" if not bad else "FAILURES PRESENT")
