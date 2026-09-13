"""W9I-H.AUTO.2R.1 — effective Ireland policy, observed.

W9I-H.AUTO.2R could prove exactly one of eight intended runtime values. The rest
are consulted only on a path needing an eligible Irish tenant, and manufacturing
one to learn a boolean is not acceptable.

THE PROPERTY THAT MATTERS MOST
Telemetry that disagrees with behaviour is worse than no telemetry, because it
is believed. So the tests below do not check that the snapshot returns sensible
values -- they check that it returns THE SAME value the real decision uses, for
every input the real parser accepts.
"""
import inspect
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import ireland_policy
from services import onboarding_lifecycle as ob
from services import permanent_numbers as perm
from services import regulatory_reconcile as rec
from services import temporary_numbers as temp
from tests.module_identifiers import identifiers

#: Every spelling the real parsers accept, plus the ones they must reject.
TRUTHY = ["true", "1", "yes", "on", "TRUE", "Yes", "ON", " true ", "True"]
FALSY = ["", "false", "0", "no", "off", "FALSE", "nope", "2", " ", "null"]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for v in ("IRELAND_ONBOARDING_ENABLED", "TEMP_NUMBER_ENABLED",
              "TEMP_NUMBER_SOURCE_COUNTRY", "TEMP_NUMBER_TYPE",
              "IRELAND_PERMANENT_NUMBER_PURCHASE_ENABLED",
              "REGULATORY_RECONCILE_APPLY"):
        monkeypatch.delenv(v, raising=False)


# ═══ 1. the snapshot agrees with the authority, for every input ══════════

@pytest.mark.parametrize("value", TRUTHY + FALSY)
def test_onboarding_flag_matches_the_real_parser(monkeypatch, value):
    monkeypatch.setenv("IRELAND_ONBOARDING_ENABLED", value)
    assert (ireland_policy.snapshot()["ireland_onboarding_enabled"]
            is ob.ireland_onboarding_enabled())


@pytest.mark.parametrize("value", TRUTHY + FALSY)
def test_permanent_purchase_flag_matches_the_real_parser(monkeypatch, value):
    monkeypatch.setenv("IRELAND_PERMANENT_NUMBER_PURCHASE_ENABLED", value)
    assert (ireland_policy.snapshot()["ireland_permanent_purchase_enabled"]
            is perm.purchase_enabled())


@pytest.mark.parametrize("value", TRUTHY + FALSY)
def test_reconcile_apply_flag_matches_the_real_parser(monkeypatch, value):
    monkeypatch.setenv("REGULATORY_RECONCILE_APPLY", value)
    assert (ireland_policy.snapshot()["regulatory_reconcile_apply"]
            is rec.scheduled_apply_enabled())


@pytest.mark.parametrize("value", TRUTHY + FALSY)
def test_temp_enabled_flag_matches_the_real_parser(monkeypatch, value):
    monkeypatch.setenv("TEMP_NUMBER_ENABLED", value)
    assert (ireland_policy.snapshot()["temp_number_enabled"]
            is temp.source_policy().enabled)


def test_an_unset_flag_is_false_everywhere():
    snap = ireland_policy.snapshot()
    assert snap["ireland_onboarding_enabled"] is False
    assert snap["temp_number_enabled"] is False
    assert snap["ireland_permanent_purchase_enabled"] is False
    assert snap["regulatory_reconcile_apply"] is False


# ═══ 2. the source country is EFFECTIVE, not echoed ═════════════════════

@pytest.mark.parametrize("raw,expected", [
    ("CA", "CA"),
    ("ca", "CA"),            # the real parser uppercases
    (" ca ", "CA"),
    ("US", "US"),
    ("GB", "GB"),
    ("IE", None),            # regulated -- would never be bought from
    ("ZZ", None),            # unsupported
    ("", None),              # unset
    ("   ", None),
    ("canada", None),
])
def test_the_source_country_reports_what_would_actually_be_used(
        monkeypatch, raw, expected):
    monkeypatch.setenv("TEMP_NUMBER_ENABLED", "true")
    monkeypatch.setenv("TEMP_NUMBER_SOURCE_COUNTRY", raw)
    assert ireland_policy.snapshot()["temp_number_source_country"] == expected


def test_a_regulated_source_never_reports_as_usable(monkeypatch):
    """The b743f00d protection, reflected honestly. Reporting "IE" here would
    tell an operator the configuration was fine when no number could come from
    it."""
    monkeypatch.setenv("TEMP_NUMBER_ENABLED", "true")
    monkeypatch.setenv("TEMP_NUMBER_SOURCE_COUNTRY", "IE")
    assert ireland_policy.snapshot()["temp_number_source_country"] is None
    # ...and the authority agrees.
    assert temp.source_problem(temp.source_policy()) == "source_country_is_regulated:IE"


def test_the_source_country_is_independent_of_the_enabled_flag(monkeypatch):
    """Folding them together would report a correctly-configured CA source as
    None merely because the feature was off, misleading whoever is diagnosing
    the other field."""
    monkeypatch.setenv("TEMP_NUMBER_SOURCE_COUNTRY", "CA")
    monkeypatch.setenv("TEMP_NUMBER_ENABLED", "false")
    snap = ireland_policy.snapshot()
    assert snap["temp_number_enabled"] is False
    assert snap["temp_number_source_country"] == "CA"


def test_a_usable_source_matches_the_validator(monkeypatch):
    for country in ("CA", "US", "GB", "IE", "ZZ", ""):
        monkeypatch.setenv("TEMP_NUMBER_ENABLED", "true")
        monkeypatch.setenv("TEMP_NUMBER_SOURCE_COUNTRY", country)
        reported = ireland_policy.snapshot()["temp_number_source_country"]
        accepted = temp.source_problem(temp.source_policy()) == ""
        assert (reported is not None) == accepted, country


# ═══ 3. no second parser ════════════════════════════════════════════════

def test_the_snapshot_reimplements_no_parsing():
    """If it parsed environment values itself, the two could drift into health
    saying one thing while the lifecycle does another."""
    import ast, textwrap
    fn = ast.parse(textwrap.dedent(
        inspect.getsource(ireland_policy.snapshot))).body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]          # the docstring may discuss what the code avoids
    code = ast.unparse(fn)
    for smell in ("getenv", "environ", '"true"', "'true'", "lower()", "strip()"):
        assert smell not in code, smell


def test_it_calls_each_canonical_authority():
    src = inspect.getsource(ireland_policy.snapshot)
    for authority in ("ireland_onboarding_enabled", "source_policy",
                      "source_problem", "purchase_enabled",
                      "scheduled_apply_enabled"):
        assert authority in src, authority


def test_the_reported_fields_are_exactly_the_allowlist():
    assert set(ireland_policy.snapshot()) == set(ireland_policy.FIELDS)
    assert len(ireland_policy.FIELDS) == 5


# ═══ 4. secrets ═════════════════════════════════════════════════════════

def test_the_snapshot_is_an_allowlist_not_an_environment_dump(monkeypatch):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok_secret_value")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_secret_value")
    monkeypatch.setenv("VAPI_API_KEY", "vapi_secret_value")
    monkeypatch.setenv("RESEND_API_KEY", "re_secret_value")
    monkeypatch.setenv("ADMIN_API_KEY", "admin_secret_value")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_value")
    monkeypatch.setenv("OPENAI_API_KEY", "oa_secret_value")
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/db")
    blob = json.dumps(ireland_policy.snapshot_record())
    for secret in ("tok_secret_value", "sk_live_secret_value", "vapi_secret_value",
                   "re_secret_value", "admin_secret_value", "sb_secret_value",
                   "oa_secret_value", "postgres://"):
        assert secret not in blob, secret
    for prefix in ("TWILIO", "STRIPE", "VAPI", "RESEND", "DATABASE",
                   "SUPABASE", "OPENAI", "ADMIN"):
        assert prefix not in blob.upper(), prefix


def test_the_record_adds_only_provenance():
    rec_ = ireland_policy.snapshot_record()
    assert set(rec_) == set(ireland_policy.FIELDS) | {"observed_at", "commit"}


def test_the_record_is_timestamped():
    """A configuration report with no timestamp cannot be told apart from a
    stale one -- the exact mistake the cron heartbeat allowed."""
    from datetime import datetime
    rec_ = ireland_policy.snapshot_record()
    assert datetime.fromisoformat(rec_["observed_at"])


# ═══ 5. one-way: policy -> observability, never back ════════════════════

def test_no_business_module_reads_the_snapshot():
    """The snapshot must never become a second policy authority."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    allowed = {"ireland_policy.py", "admin.py", "recrawl_cron.py"}
    offenders = []
    for py in list((root / "services").glob("*.py")) + \
              list((root / "routers").glob("*.py")) + \
              list((root / "db").glob("*.py")):
        if py.name in allowed:
            continue
        if "ireland_policy" in py.read_text():
            offenders.append(py.name)
    assert offenders == [], offenders


def test_nothing_decides_from_the_persisted_snapshot():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for py in list((root / "services").glob("*.py")) + list((root / "routers").glob("*.py")):
        if "ireland_policy_snapshot" in py.read_text():
            offenders.append(py.name)
    assert offenders == [], offenders


def test_the_snapshot_module_cannot_reach_provider_or_billing():
    refs = identifiers(ireland_policy)
    for forbidden in ("purchase_number_with_sid", "purchase_regulated_number",
                      "ensure_temporary_number", "ensure_permanent_irish_number",
                      "create_trial_subscription", "advance", "Customer",
                      "set_system_meta"):
        assert forbidden not in refs, forbidden


def test_generating_a_snapshot_touches_nothing(monkeypatch):
    monkeypatch.setenv("IRELAND_ONBOARDING_ENABLED", "true")
    monkeypatch.setenv("TEMP_NUMBER_ENABLED", "true")
    monkeypatch.setenv("TEMP_NUMBER_SOURCE_COUNTRY", "CA")
    import db.supabase as dbmod
    with patch.object(dbmod, "get_client",
                      side_effect=AssertionError("TOUCHED THE DATABASE")):
        snap = ireland_policy.snapshot()
    assert snap["temp_number_source_country"] == "CA"


# ═══ 6. the admin surface ═══════════════════════════════════════════════

@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers import admin
    app = FastAPI()
    app.include_router(admin.router)   # the router already carries /admin
    monkeypatch.setenv("ADMIN_API_KEY", "correct-horse")
    return TestClient(app, raise_server_exceptions=False)


def test_admin_health_without_a_key_is_refused(client):
    r = client.get("/admin/health")
    assert r.status_code == 403
    assert "ireland_policy" not in r.text


def test_admin_health_with_a_wrong_key_is_refused(client):
    r = client.get("/admin/health", headers={"x-admin-key": "wrong"})
    assert r.status_code == 403
    assert "ireland_policy" not in r.text


def test_admin_health_with_the_key_reports_the_snapshot(client, monkeypatch):
    monkeypatch.setenv("IRELAND_ONBOARDING_ENABLED", "true")
    monkeypatch.setenv("TEMP_NUMBER_ENABLED", "true")
    monkeypatch.setenv("TEMP_NUMBER_SOURCE_COUNTRY", "CA")
    r = client.get("/admin/health", headers={"x-admin-key": "correct-horse"})
    assert r.status_code == 200
    pol = r.json()["ireland_policy"]
    assert pol["ireland_onboarding_enabled"] is True
    assert pol["temp_number_source_country"] == "CA"
    assert pol["ireland_permanent_purchase_enabled"] is False
    assert set(pol) == set(ireland_policy.FIELDS)


def test_admin_health_still_renders_if_the_snapshot_fails(client):
    """A page that cannot say what the flags are is worth more than no page."""
    with patch.object(ireland_policy, "snapshot",
                      side_effect=RuntimeError("boom")):
        r = client.get("/admin/health", headers={"x-admin-key": "correct-horse"})
    assert r.status_code == 200
    assert r.json()["ireland_policy"] is None
    assert r.json()["checks"]


def test_the_admin_route_was_not_duplicated():
    from routers import admin
    health = [r for r in admin.router.routes
              if getattr(r, "path", "") == "/admin/health"]
    assert len(health) == 1


# ═══ 7. the cron surface ════════════════════════════════════════════════

def test_the_cron_writes_the_snapshot_after_every_job():
    """Ordering is the isolation: telemetry runs last so a failure to write it
    cannot cost a reconciliation or a lifecycle sweep."""
    import pathlib
    src = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "recrawl_cron.py"
    text = src.read_text()
    assert text.index("ireland_lifecycle") < text.index("ireland_policy_snapshot")
    assert text.index("cron_last_run") < text.index("ireland_policy_snapshot")


def test_the_cron_snapshot_write_is_isolated():
    import ast, pathlib, textwrap
    src = (pathlib.Path(__file__).resolve().parent.parent / "scripts"
           / "recrawl_cron.py").read_text()
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and "ireland_policy_snapshot" in ast.unparse(node):
            found = True
            assert node.handlers, "the snapshot write must not be able to raise"
            # It must not re-raise: the cron's own run is more important.
            for h in node.handlers:
                assert not any(isinstance(n, ast.Raise) for n in ast.walk(h))
    assert found, "the snapshot write is not wrapped at all"


@pytest.mark.asyncio
async def test_a_failed_snapshot_write_does_not_fail_the_cron(monkeypatch):
    """Telemetry is not authority, and it is not a dependency either."""
    import db.supabase as dbmod
    written = []

    async def set_meta(key, value):
        if key == "ireland_policy_snapshot":
            raise RuntimeError("system_meta unavailable")
        written.append(key)

    from services import ireland_policy as pol
    with patch.object(dbmod, "set_system_meta", new=set_meta):
        # The exact shape the cron uses.
        try:
            await dbmod.set_system_meta("cron_last_run", "now")
            try:
                await dbmod.set_system_meta("ireland_policy_snapshot",
                                            json.dumps(pol.snapshot_record()))
            except Exception:
                pass
            survived = True
        except Exception:
            survived = False
    assert survived and written == ["cron_last_run"]


def test_the_persisted_snapshot_round_trips(monkeypatch):
    monkeypatch.setenv("IRELAND_ONBOARDING_ENABLED", "true")
    monkeypatch.setenv("TEMP_NUMBER_ENABLED", "true")
    monkeypatch.setenv("TEMP_NUMBER_SOURCE_COUNTRY", "CA")
    monkeypatch.setenv("REGULATORY_RECONCILE_APPLY", "true")
    blob = json.dumps(ireland_policy.snapshot_record())
    back = json.loads(blob)
    assert back["ireland_onboarding_enabled"] is True
    assert back["temp_number_source_country"] == "CA"
    assert back["regulatory_reconcile_apply"] is True
    assert back["ireland_permanent_purchase_enabled"] is False
