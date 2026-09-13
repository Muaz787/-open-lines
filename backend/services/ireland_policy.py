"""What the Ireland policy flags EFFECTIVELY resolve to, for observation only
(W9I-H.AUTO.2R.1).

WHY THIS EXISTS
W9I-H.AUTO.2R could prove exactly one of eight intended runtime values. The
others are consulted only on a path that needs an eligible Irish tenant, and
manufacturing one to expose a boolean is not an acceptable way to learn it. So
the values are reported from the processes that hold them.

THE DIRECTION IS ONE-WAY, AND IT MATTERS

    POLICY  ──>  OBSERVABILITY

never the reverse. Nothing here decides anything. Every value is read through
the SAME function the real decision uses, so the two cannot drift into a state
where health says one thing and the lifecycle does another -- which would be
worse than having no telemetry, because it would be believed.

That is also why this module reimplements no parsing. It calls
ireland_onboarding_enabled(), source_policy(), source_problem(),
purchase_enabled() and scheduled_apply_enabled(), and reports what they say.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: The ONLY fields this module may ever report. An explicit allowlist rather
#: than a filtered environment dump: a dump is one careless addition away from
#: printing a provider credential into a log or a health page.
FIELDS = ("ireland_onboarding_enabled", "temp_number_enabled",
          "temp_number_source_country", "ireland_permanent_purchase_enabled",
          "regulatory_reconcile_apply")


def snapshot() -> dict:
    """The effective Ireland policy this process is running with.

    `temp_number_source_country` is the country a temporary number would
    ACTUALLY be bought from, not the raw environment string: a value the
    canonical validator rejects -- unset, unsupported, or a regulated country --
    reports as None, because no number would ever come from it.

    It is deliberately independent of `temp_number_enabled`, which has its own
    field. Folding the two together would report a correctly-configured CA
    source as None merely because the feature was switched off, and an operator
    diagnosing one would be misled about the other.
    """
    from services import onboarding_lifecycle as ob
    from services import permanent_numbers as perm
    from services import regulatory_reconcile as rec
    from services import temporary_numbers as temp

    policy = temp.source_policy()

    # Ask the canonical validator about the COUNTRY alone, by handing it a
    # policy that differs only in being enabled. Reusing source_problem here is
    # the point: the rule that rejects IE lives in one place and is applied by
    # that place, not restated by this one.
    country_probe = temp.TemporarySource(
        enabled=True, iso_country=policy.iso_country,
        number_type=policy.number_type)
    country_usable = temp.source_problem(country_probe) == ""

    return {
        "ireland_onboarding_enabled": bool(ob.ireland_onboarding_enabled()),
        "temp_number_enabled": bool(policy.enabled),
        "temp_number_source_country": policy.iso_country if country_usable else None,
        "ireland_permanent_purchase_enabled": bool(perm.purchase_enabled()),
        "regulatory_reconcile_apply": bool(rec.scheduled_apply_enabled()),
    }


def snapshot_record(*, observed_at: str = "", commit: str = "") -> dict:
    """The snapshot plus when and by which build it was observed.

    A configuration report with no timestamp cannot be told apart from a stale
    one, and that is exactly the mistake W9I-H.AUTO.2R made with the cron
    heartbeat -- a value that looked current and predated the deployment.
    """
    from datetime import datetime, timezone
    import os
    return {
        **snapshot(),
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat(),
        "commit": commit or os.getenv("RAILWAY_GIT_COMMIT_SHA", "")
                  or os.getenv("GIT_COMMIT_SHA", ""),
    }
