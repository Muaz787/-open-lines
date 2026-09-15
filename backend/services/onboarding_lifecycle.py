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
# GB, AU and NZ were previously excluded here on the stated grounds that nobody
# had measured them. They have now been measured: Twilio's Regulation API was
# queried for local BUSINESS numbers in every country offered at signup, and the
# supporting documents required are
#
#   CA  none                      US  none
#   GB  business_address          IE  business_address_info
#   NZ  business_name_info, business_address_proof_info
#   AU  business_name_info, business_address_proof_info,
#       name_of_auth_rep_info, auth_of_auth_rep_info
#
# so all four are regulated as a matter of fact, and this set now says so.
REGULATED_COUNTRIES = frozenset({"IE", "GB", "AU", "NZ"})

# BEING REGULATED AND BEING SERVABLE ARE DIFFERENT FACTS, AND CONFLATING THEM
# WOULD SELL SOMEBODY THE WRONG COUNTRY'S NUMBER.
#
# The pipeline that carries a regulated tenant from filing to a live number is
# Ireland's: permanent_numbers searches and buys with a hardcoded "IE", and its
# held-number filter treats an unknown country as "match everything". A GB tenant
# admitted to that pipeline would, on approval, have an Irish number bought for
# them -- a silent wrong-country purchase, which is worse than the loud failure
# at Twilio that not listing them produced.
#
# So this second set is what we can actually deliver end to end. A regulated
# country outside it is refused at signup, honestly and before anything is
# created, rather than admitted to a pipeline shaped for somewhere else. Adding a
# country here is the LAST step of making it work, never the first.
REGULATED_SERVABLE = frozenset({"IE"})


def needs_regulatory_clearance(iso_country: str) -> bool:
    """Must a regulator be satisfied before this country can hold a number?"""
    return str(iso_country or "").strip().upper() in REGULATED_COUNTRIES


def can_serve_regulated(iso_country: str) -> bool:
    """Can we carry this regulated country all the way to a live number?

    False for a country we know to be regulated but have not built the path for.
    Says nothing about unregulated countries, which never reach this question.
    """
    return str(iso_country or "").strip().upper() in REGULATED_SERVABLE


def initial_state(iso_country: str) -> str:
    """The state a newly created tenant starts in, from its country alone."""
    return REGULATORY_REQUIRED if needs_regulatory_clearance(iso_country) else PROVISIONING


def is_resumable(state: str) -> bool:
    return str(state or "") in RESUMABLE_STATES


# ── rollout control ────────────────────────────────────────────────────────

def ireland_onboarding_enabled() -> bool:
    """Is the Irish onboarding path open to the public?

    THE AUTHORITATIVE IRELAND POLICY, which this flag opens:

      * Public onboarding. An Irish business signs up through the ordinary form.
        No pilot grant, no invite, no operator step -- migration 033's grant
        mechanism is the way past a CLOSED gate and is dormant while this is on.
      * Free temporary test access WHILE A GENUINE REGULATORY REVIEW IS PENDING.
        Both halves are load-bearing: entitlement comes from a Bundle the
        provider is actually holding, never from the country, the account or a
        form having been opened.
      * THE 7-DAY TRIAL STARTS ONLY AFTER THE PERMANENT +353 IS ACTIVE --
        approval verified directly at the provider, number acquired, routing and
        Vapi configured, health PASS, canonical permanent row ACTIVE. Nothing
        earlier starts it: not signup, not the card, not the filing, not the
        Bundle entering review, and NOT the temporary test line, however long
        the customer has been using it.

    W9I-G.1 implemented that deferral and W9I-H.PRE measured it; this docstring
    previously said the opposite, which was true only before those gates landed.

    Separate from IRELAND_PERMANENT_NUMBER_PURCHASE_ENABLED, which governs
    whether we are willing to buy Irish numbering commercially. They move
    independently and for different reasons.
    """
    return os.getenv("IRELAND_ONBOARDING_ENABLED", "false").strip().lower() in (
        "1", "true", "yes", "on")
