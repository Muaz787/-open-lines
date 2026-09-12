"""Where a tenant is in onboarding, and which countries can get a number today.

WHY THIS EXISTS
Until now a tenant row was the LAST thing signup created, so "a tenant exists"
and "onboarding finished" were the same fact and neither needed recording. That
works only while every country can be provisioned in one pass. Ireland cannot: a
local Irish number needs a validated address and an approved regulatory Bundle,
and both are keyed on a tenant_id by composite foreign key -- so the tenant has
to exist first, and it has to be able to sit there, valid and un-numbered, while
the customer supplies compliance information.

An Irish tenant with no phone number is NOT a broken tenant. That is the whole
point of the column this module names.

DELIBERATELY SMALL. Three states, on the tenants row, not a table:
  * the value is one fact about one tenant, and a table would add a join and a
    second place for it to disagree;
  * `tenants` already carries the rest of the onboarding scalars;
  * the regulatory span is ALREADY a state machine on
    tenant_regulatory_profiles.state, and duplicating any of it here would give
    two answers to the same question. This column stops at the boundary: "does a
    number exist yet, and if not, why not".

NOT is_active. `is_active` says the account is not closed or suspended and is
what the trial and reclaim paths read. This says setup has finished. A tenant can
be is_active=true and still mid-onboarding, which is exactly the Irish case.
"""
from __future__ import annotations

import os

# ── the three states ───────────────────────────────────────────────────────

#: The tenant exists and telephony is still owed. Every failed or interrupted
#: attempt lands here, which is what makes a retry a RESUME rather than a second
#: signup. There is deliberately no separate `failed` state: a failure that left
#: the tenant behind is retryable by definition, and a terminal one would need an
#: operator to clear it before the customer could try again.
PROVISIONING = "provisioning"

#: The tenant's country cannot be given a number until a regulator is satisfied.
#: A VALID resting state, not an error: no number, possibly no regulatory data
#: yet, and nothing wrong. W9I-C gives the customer the form; this gate only
#: makes the state expressible.
REGULATORY_REQUIRED = "regulatory_required"

#: Setup finished: a routable number exists and the assistant answers it.
ACTIVE = "active"

STATES = (PROVISIONING, REGULATORY_REQUIRED, ACTIVE)

#: Onboarding is unfinished -- a retry may resume into the same tenant.
RESUMABLE_STATES = (PROVISIONING, REGULATORY_REQUIRED)


# ── which countries can be provisioned in one pass ─────────────────────────
#
# MEASURED, not assumed. W9C bought and released real numbers to establish this,
# and W9H-QA.2 confirmed it again: an Irish local number is refused at PURCHASE
# time unless it carries a validated AddressSid and an approved Bundle, and
# Twilio exposes no way to learn that beforehand. So Ireland cannot be a branch
# inside the number search -- it has to divert before telephony is touched.
#
# GB, AU and NZ are NOT listed as regulated here, and that is a deliberate
# limit on what this gate claims: nobody has measured them. They keep today's
# behaviour exactly, and if one of them turns out to need a bundle it will fail
# the same way Ireland did -- loudly, at purchase, on a tenant that now survives
# the failure and can be resumed.
REGULATED_COUNTRIES = frozenset({"IE"})


def needs_regulatory_clearance(iso_country: str) -> bool:
    """Must a regulator be satisfied before this country can hold a number?"""
    return str(iso_country or "").strip().upper() in REGULATED_COUNTRIES


def initial_state(iso_country: str) -> str:
    """The state a newly created tenant starts in, from its country alone."""
    return REGULATORY_REQUIRED if needs_regulatory_clearance(iso_country) else PROVISIONING


def is_resumable(state: str) -> bool:
    return str(state or "") in RESUMABLE_STATES


# ── rollout control ────────────────────────────────────────────────────────

def ireland_onboarding_enabled() -> bool:
    """Is the Irish onboarding path open to the public yet?

    OFF by default, and the reason is billing rather than telephony. The approved
    Ireland trial policy is that the 7-day trial starts only once a permanent
    +353 number is acquired, configured, health-checked and active -- and that
    change belongs to a later gate. Until it lands, an Irish signup that reached
    the billing block would start a trial clock at signup, against a tenant that
    cannot receive a call for days. So the path stays closed to the public and
    open to internal QA, which is strictly better than today's behaviour: right
    now Ireland is offered in the form and fails with a raw Twilio AddressSid
    error after a sub-account has already been created.
    """
    return os.getenv("IRELAND_ONBOARDING_ENABLED", "false").strip().lower() in (
        "1", "true", "yes", "on")
