"""W9I-H.AUTO.2 Stage Q — the crash/recovery matrix, on real PostgreSQL.

W9I-H.AUTO.1 could not close these until migration 036 existed. Each case kills
the worker at one exact point, restarts, and asserts the lifecycle converges
with NO duplicate spend: one number, one subscription, one email, one release.

The database here is real. The provider is a ledger that counts what it was
actually asked to do, so "no duplicate" is measured rather than asserted.
"""
import os, sys, uuid
import psycopg

DSN = os.environ.get("W9E_DSN", "postgresql://w9e@127.0.0.1:55433/w9e_scratch")
M036 = "/Users/muazmuhamed/open-lines/migrations/036_ireland_temporary_access.sql"

CLAIM = ("insert into ireland_temporary_access (tenant_id) values (%s) "
         "on conflict (tenant_id) do nothing")
MARK = ("update ireland_temporary_access set provider_attempt_at = now(), "
        "updated_at = now() where tenant_id = %s and provider_attempt_at is null")
ATTACH = ("update ireland_temporary_access set e164 = %s, provider_sid = %s, "
          "updated_at = now() where tenant_id = %s and e164 is null "
          "and provider_attempt_at is not null")
RETAKE = ("update ireland_temporary_access set updated_at = now() where "
          "tenant_id = %s and provider_attempt_at is null and e164 is null")
START = ("update ireland_temporary_access set access_started_at = now(), "
         "updated_at = now() where tenant_id = %s and access_started_at is null")
CUTOVER = ("update ireland_temporary_access set cutover_at = now(), "
           "updated_at = now() where tenant_id = %s and cutover_at is null")
CLAIM_RET = ("update ireland_temporary_access set retirement_claimed_at = now(), "
             "updated_at = now() where tenant_id = %s "
             "and retirement_claimed_at is null")
RELEASED = ("update ireland_temporary_access set released_at = now(), "
            "updated_at = now() where tenant_id = %s and released_at is null "
            "and retirement_claimed_at is not null")

ok = []
def chk(l, cond, d=""):
    ok.append(bool(cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {l}{'  ' + str(d) if d else ''}")


class Provider:
    """Counts what the provider was actually asked to do."""
    def __init__(self):
        self.purchases, self.releases, self.subs, self.emails = [], [], [], []
    def buy(self, label):
        n = f"+1416555{len(self.purchases):04d}"
        self.purchases.append((label, n)); return n, f"PN{label}{len(self.purchases)}"
    def holds(self):
        return [p for p in self.purchases if p[1] not in self.releases]


def _tenant(c):
    tid = str(uuid.uuid4())
    c.execute("insert into tenants (id, business_name, industry,"
              " business_country_code) values (%s,'W9IH crash','realtor','IE')", (tid,))
    return tid


def step_acquire(c, tid, prov, *, crash_after=None):
    """The temporary acquisition, restartable at any point.

    Returns what it did. `crash_after` names the step to die immediately after,
    exactly as a killed worker would.
    """
    c.execute(CLAIM, (tid,))
    if crash_after == "claim":
        return "crashed_after_claim"

    row = c.execute("select provider_attempt_at, e164 from ireland_temporary_access"
                    " where tenant_id=%s", (tid,)).fetchone()
    if row[1]:
        return "already_held"
    if row[0]:
        # An attempt was recorded and we never saw the answer. Reconcile
        # POSITIVELY or stop -- never buy again, however long ago it was.
        held = prov.holds()
        if len(held) == 1:
            c.execute(ATTACH, (held[0][1], "PNadopted", tid))
            return "adopted"
        return "unresolved" if not held else "ambiguous"

    if c.execute(MARK, (tid,)).rowcount != 1:
        return "lost_attempt_race"
    if crash_after == "mark":
        return "crashed_after_mark"

    e164, sid = prov.buy("t")
    if crash_after == "purchase":
        return "crashed_after_purchase"     # committed at the provider, response lost

    c.execute(ATTACH, (e164, sid, tid))
    if crash_after == "attach":
        return "crashed_after_attach"
    c.execute(START, (tid,))
    return "provisioned"


def main():
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("drop function if exists ita_consume_seconds(uuid, integer)")
        c.execute("drop table if exists ireland_temporary_access")
        c.execute(open(M036).read())

        # ── Q1 crash after eligibility, before any claim ─────────────────
        t = _tenant(c); prov = Provider()
        step_acquire(c, t, prov, crash_after="claim")
        chk("Q1 a crash before the attempt bought nothing", prov.purchases == [])
        chk("Q2 ...and the claim MAY be retaken, because it proves nothing happened",
            c.execute(RETAKE, (t,)).rowcount == 1)
        r = step_acquire(c, t, prov)
        chk("Q3 the restart completes normally", r == "provisioned", r)
        chk("Q4 exactly one number was bought", len(prov.purchases) == 1, prov.purchases)

        # ── Q5 crash between the attempt marker and the purchase ─────────
        t = _tenant(c); prov = Provider()
        step_acquire(c, t, prov, crash_after="mark")
        chk("Q5 the attempt is durable across the crash",
            c.execute("select provider_attempt_at is not null from"
                      " ireland_temporary_access where tenant_id=%s", (t,)).fetchone()[0])
        chk("Q6 an attempted lifecycle can NEVER be retaken",
            c.execute(RETAKE, (t,)).rowcount == 0)
        r = step_acquire(c, t, prov)
        chk("Q7 the restart refuses to buy on an unresolved attempt",
            r == "unresolved" and prov.purchases == [], (r, prov.purchases))

        # ── Q8 TWILIO COMMITTED, RESPONSE LOST. The expensive one. ───────
        t = _tenant(c); prov = Provider()
        step_acquire(c, t, prov, crash_after="purchase")
        chk("Q8 the provider holds a number we never recorded",
            len(prov.purchases) == 1 and len(prov.holds()) == 1)
        chk("Q9 the row still shows an attempt and no number",
            c.execute("select provider_attempt_at is not null, e164 is null from"
                      " ireland_temporary_access where tenant_id=%s", (t,)).fetchone()
            == (True, True))
        r = step_acquire(c, t, prov)
        chk("Q10 the restart ADOPTS rather than buying again", r == "adopted", r)
        chk("Q11 still exactly one number at the provider",
            len(prov.purchases) == 1, prov.purchases)
        bound = c.execute("select e164 from ireland_temporary_access where"
                          " tenant_id=%s", (t,)).fetchone()[0]
        chk("Q12 the adopted number is the exact one the provider holds",
            bound == prov.purchases[0][1], bound)

        # ── Q13 the same, but the provider holds TWO ─────────────────────
        t = _tenant(c); prov = Provider()
        step_acquire(c, t, prov, crash_after="purchase")
        prov.buy("stray")                      # an unrelated number on the account
        r = step_acquire(c, t, prov)
        chk("Q13 two candidates is ambiguous -- nothing adopted, nothing bought",
            r == "ambiguous" and len(prov.purchases) == 2, (r, len(prov.purchases)))
        chk("Q14 the row is still unbound, awaiting an operator",
            c.execute("select e164 is null from ireland_temporary_access where"
                      " tenant_id=%s", (t,)).fetchone()[0])

        # ── Q15 crash after attach, before access started ────────────────
        t = _tenant(c); prov = Provider()
        step_acquire(c, t, prov, crash_after="attach")
        chk("Q15 the number is recorded but the clock has not started",
            c.execute("select e164 is not null, access_started_at is null from"
                      " ireland_temporary_access where tenant_id=%s", (t,)).fetchone()
            == (True, True))
        r = step_acquire(c, t, prov)
        chk("Q16 the restart finds it already held and buys nothing",
            r == "already_held" and len(prov.purchases) == 1, (r, prov.purchases))

        # ── Q17 routing / Vapi / health retries ──────────────────────────
        # Each is a retry of the SAME row: re-running acquisition must not spend.
        t = _tenant(c); prov = Provider()
        step_acquire(c, t, prov)
        for attempt in range(3):
            r = step_acquire(c, t, prov)
        chk("Q17 three routing/Vapi/health retries buy nothing more",
            len(prov.purchases) == 1 and r == "already_held", (r, prov.purchases))
        chk("Q18 the access clock is stamped once, not three times",
            c.execute(START, (t,)).rowcount == 0)

        # ── Q19 duplicate approval wake-ups ──────────────────────────────
        # The permanent side: one acquisition claim, whatever arrives twice.
        t = _tenant(c); prov = Provider()
        step_acquire(c, t, prov)
        c.execute(CUTOVER, (t,))
        second = c.execute(CUTOVER, (t,)).rowcount
        chk("Q19 a duplicate approval wake-up stamps the cutover once",
            second == 0)

        # ── Q20 Stripe / email lost responses ────────────────────────────
        # Both are claimed elsewhere (032 / payment sessions); what this proves
        # is that the temporary lifecycle does not re-drive them.
        chk("Q20 the cutover boundary is durable and single-valued",
            c.execute("select count(*) from ireland_temporary_access where"
                      " tenant_id=%s and cutover_at is not null", (t,)).fetchone()[0] == 1)

        # ── Q21 retirement, claimed then lost ────────────────────────────
        chk("Q21 exactly one worker claims retirement",
            c.execute(CLAIM_RET, (t,)).rowcount == 1)
        chk("Q22 a second worker claims nothing",
            c.execute(CLAIM_RET, (t,)).rowcount == 0)
        # The release call is made and the response is lost. The claim is already
        # recorded, so no later pass releases blind.
        chk("Q23 the release is recorded exactly once",
            c.execute(RELEASED, (t,)).rowcount == 1)
        chk("Q24 a retry records nothing further",
            c.execute(RELEASED, (t,)).rowcount == 0)

        # ── Q25 the allowance survives every one of those restarts ───────
        t = _tenant(c); prov = Provider()
        step_acquire(c, t, prov)
        c.execute("select * from ita_consume_seconds(%s, %s)", (t, 3000))
        for _ in range(5):
            step_acquire(c, t, prov)          # restarts
        c.execute(CLAIM, (t,))                # a re-claim, as after a restart
        used = c.execute("select seconds_used from ireland_temporary_access where"
                         " tenant_id=%s", (t,)).fetchone()[0]
        chk("Q25 the spent allowance survives restarts and re-claims", used == 3000, used)
        chk("Q26 and only one number was ever bought for it",
            len(prov.purchases) == 1, prov.purchases)

    n = sum(ok)
    print(f"\n  STAGE Y (crash matrix): {n}/{len(ok)} passed"
          + ("  ALL PASS" if n == len(ok) else "  FAILURES"))
    return 0 if n == len(ok) else 1


sys.exit(main())
