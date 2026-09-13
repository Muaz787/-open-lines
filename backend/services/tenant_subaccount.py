"""The tenant's ONE durable Twilio sub-account (W9I-E Stage F).

WHY THIS EXISTS
W9I-B returns an Irish signup at `regulatory_required` BEFORE Step 3, which is
where the sub-account is created. So an Irish tenant had none -- and every
regulatory resource needs one: `regulatory_engine._tenant_client` returns None
without credentials, so W9I-C's address validation would have failed for a real
customer with "verification_needs_review". The live QA in W9I-C only worked
because a disposable sub-account was created by hand.

ONE SUB-ACCOUNT PER TENANT, for its whole life: the Address, the EndUser, the
SupportingDocument, the Bundle, the temporary test number and later the permanent
+353. Splitting them across accounts would break the thing W9C measured -- Numbers
v2 is CREDENTIAL-scoped, so a Bundle created under one account is invisible to
another's credentials, and a number cannot be bought against a Bundle it cannot
see.

WHY IT IS NOT A PLAIN "CREATE IF MISSING"
Two concurrent requests both reading "no sub-account" both create one, and the
loser's is a live, billable, invisible orphan holding regulatory resources nobody
will ever look at again. That is the same defect W9H-QA.3 measured for Addresses,
so it gets the same shape of answer:

    search by a marker only we could have written
        -> adopt what is already there, or create
        -> fenced attach decides the single winner
        -> the loser closes the account it created

The marker is the FriendlyName, which Twilio filters server-side. It carries the
tenant id, so a crashed worker's account is findable rather than orphaned -- the
question "did I already create one?" has an answer at the provider, not just in a
database row that may never have been written.
"""
from __future__ import annotations

import logging

from db.supabase import get_client
from services import telephony

logger = logging.getLogger(__name__)

OK = "ok"
PROVIDER_UNAVAILABLE = "provider_unavailable"
NOT_FOUND = "tenant_not_found"

#: The FriendlyName marker. Deliberately carries the tenant id and nothing else
#: identifying -- a business name is customer data and changes, a tenant id does
#: not. Twilio's FriendlyName limit on Accounts is 64 characters; a uuid plus this
#: prefix is 47, asserted below so a future prefix edit cannot silently truncate
#: the marker and break reconciliation.
MARKER_PREFIX = "OpenLines tenant "
MARKER_MAX = 64


def marker_for(tenant_id: str) -> str:
    marker = f"{MARKER_PREFIX}{tenant_id}"
    assert len(marker) <= MARKER_MAX, f"sub-account marker too long: {len(marker)}"
    return marker


async def ensure(tenant: dict) -> dict:
    """The tenant's sub-account SID and token, creating it at most once.

    Idempotent and safe to call from anywhere that needs provider credentials.
    Returns {"status": OK, "sid": ..., "auth_token": ..., "created": bool}.
    """
    tenant_id = str(tenant.get("id") or "")
    if not tenant_id:
        return {"status": NOT_FOUND, "sid": "", "auth_token": "", "created": False}

    sid = str(tenant.get("twilio_subaccount_sid") or "").strip()
    tok = str(tenant.get("twilio_auth_token") or "").strip()
    if sid and tok:
        return {"status": OK, "sid": sid, "auth_token": tok, "created": False}

    marker = marker_for(tenant_id)

    # ── 1. HAS ONE ALREADY BEEN CREATED FOR THIS TENANT? ──────────────────
    # Asked at the PROVIDER, not only in our row. A worker that created an
    # account and died before writing the row left a real account behind; this is
    # what finds it instead of creating a second one.
    try:
        existing = telephony._master_client().api.accounts.list(
            friendly_name=marker, limit=5)
    except Exception as e:
        # Not knowing is not a licence to create. A second account here is
        # billable, invisible and holds regulatory resources nobody revisits.
        logger.error("sub-account reconciliation failed for tenant %s: %s",
                     tenant_id, e)
        return {"status": PROVIDER_UNAVAILABLE, "sid": "", "auth_token": "",
                "created": False}

    live = [a for a in existing if str(getattr(a, "status", "")) != "closed"]
    if live:
        if len(live) > 1:
            # Should be impossible: the fenced attach below admits one winner and
            # the loser closes its own. Loud rather than silently picking one.
            logger.error("tenant %s has %d live sub-accounts carrying its marker "
                         "-- reconcile by hand", tenant_id, len(live))
        account = live[0]
        adopted = {"sid": str(account.sid),
                   "auth_token": str(getattr(account, "auth_token", "") or "")}
        created = False
    else:
        try:
            account = telephony._master_client().api.accounts.create(
                friendly_name=marker)
        except Exception as e:
            logger.error("sub-account creation failed for tenant %s: %s", tenant_id, e)
            return {"status": PROVIDER_UNAVAILABLE, "sid": "", "auth_token": "",
                    "created": False}
        adopted = {"sid": str(account.sid),
                   "auth_token": str(getattr(account, "auth_token", "") or "")}
        created = True

    # ── 2. THE FENCED ATTACH DECIDES THE WINNER ───────────────────────────
    # Only a row that still has NO sub-account may take ours. PostgREST returns
    # the rows it changed, so exactly one concurrent caller sees a row back.
    changed = (get_client().table("tenants")
               .update({"twilio_subaccount_sid": adopted["sid"],
                        "twilio_auth_token": adopted["auth_token"]})
               .eq("id", tenant_id)
               .is_("twilio_subaccount_sid", "null")
               .execute().data or [])

    if changed:
        logger.info("Attached Twilio sub-account to tenant %s (created=%s)",
                    tenant_id, created)
        return {"status": OK, "sid": adopted["sid"],
                "auth_token": adopted["auth_token"], "created": created}

    # Someone else won. Re-read to find out what the tenant actually has.
    rows = (get_client().table("tenants")
            .select("twilio_subaccount_sid, twilio_auth_token")
            .eq("id", tenant_id).limit(1).execute().data or [])
    winner_sid = str((rows[0] if rows else {}).get("twilio_subaccount_sid") or "")
    winner_tok = str((rows[0] if rows else {}).get("twilio_auth_token") or "")

    if created and winner_sid and winner_sid != adopted["sid"]:
        # We created an account and lost the race. Closing it here is what keeps
        # "one sub-account per tenant" true rather than merely intended -- a live
        # loser would bill and would be the account nobody's credentials read.
        try:
            telephony._master_client().api.accounts(adopted["sid"]).update(status="closed")
            logger.warning("Closed the sub-account this worker lost the race with "
                           "for tenant %s", tenant_id)
        except Exception as e:
            logger.error("Could not close the losing sub-account for tenant %s: %s",
                         tenant_id, e)

    if not (winner_sid and winner_tok):
        return {"status": PROVIDER_UNAVAILABLE, "sid": "", "auth_token": "",
                "created": False}
    return {"status": OK, "sid": winner_sid, "auth_token": winner_tok,
            "created": False}
