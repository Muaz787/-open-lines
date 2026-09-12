"""Deployment identity for release verification (W9F.1).

WHY THIS EXISTS. Three gates in a row could not answer "which commit is Railway
actually serving?" -- there is no Railway CLI or token in the working environment and
no route exposed it, so every release had to be verified by inference. One field on
/health fixes that permanently.

WHY IT LIVES HERE RATHER THAN IN main.py. main.py cannot be imported by the test
suite (conftest stubs third-party packages and slowapi does not survive it), so logic
placed there is untestable. This module has no dependencies beyond os.

SAFETY. The value is only ever emitted if it LOOKS LIKE a commit SHA. That is the
important property: /health is public and unauthenticated, so echoing whatever an
environment variable happens to contain would turn a mis-set variable into an
information leak. A non-SHA value is treated as absent, not passed through.
"""
from __future__ import annotations

import os
import re

#: Checked in order. RAILWAY_GIT_COMMIT_SHA is Railway's own auto-injected variable
#: ("the git SHA of the commit that triggered the deployment"), provided without
#: opt-in when the deploy came from a GitHub trigger -- which is how this service
#: deploys. GIT_COMMIT_SHA is the generic escape hatch for anywhere else (a local
#: container, a future host) and is deliberately the only alias: a long list of
#: guesses would just widen the surface for a mis-set variable.
COMMIT_ENV_VARS = ("RAILWAY_GIT_COMMIT_SHA", "GIT_COMMIT_SHA")

#: A full git SHA is 40 hex characters; an abbreviated one is conventionally 7-12.
#: The 13-39 band is deliberately EXCLUDED rather than accepted as "some abbreviated
#: form", because that band is where all-hex SECRETS live. A Twilio Account SID is
#: "AC" + 32 hex, which lower-cases to 34 characters that are entirely hex and would
#: sail through a naive ^[0-9a-f]{7,40}$ -- a test written for this module caught
#: exactly that. An MD5 digest (32) is in the same band. Losing the ability to
#: publish an unusually-abbreviated SHA costs nothing; publishing an account
#: identifier on an unauthenticated endpoint is not recoverable.
_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{7,12})$")


def deployment_commit() -> str | None:
    """The commit SHA this process was deployed from, or None when not knowable.

    Never raises, never invents a value, and never returns anything that is not a
    well-formed git SHA.
    """
    for name in COMMIT_ENV_VARS:
        raw = os.environ.get(name)
        if raw is None:
            continue
        value = str(raw).strip().lower()
        if _SHA.match(value):
            return value
        # Present but not a SHA: a placeholder like "unknown", a truncated build
        # arg, or a variable someone pointed at the wrong thing. Treat as absent
        # rather than publishing it on an unauthenticated endpoint.
    return None


def health_payload(*, environment: str, version: str = "0.1.0") -> dict:
    """The /health body. `commit` is present only when it could be established.

    Health must never fail because deployment metadata is missing -- an unknown
    commit is a gap in observability, not an unhealthy service.
    """
    payload: dict = {"status": "ok", "version": version, "environment": environment}
    commit = deployment_commit()
    if commit:
        payload["commit"] = commit
    return payload
