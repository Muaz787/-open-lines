"""The scheduled service must say what Ireland configuration it holds.

THE DEFECT THIS CLOSES
Railway gives the web and scheduled services SEPARATE environment variables.
recrawl_cron runs ireland_lifecycle.run_scheduled() and
regulatory_reconcile.run_scheduled(), so it reads the Ireland flags itself --
but its preflight did not list them, so nothing on that service ever printed
them.

/admin/health computes ireland_policy in the WEB service. A flag set there and
not on the scheduled one therefore reads as ON everywhere an operator can look,
while the sweep that needs it is silently refused. That is precisely the
NUMBER_RECLAIM_ENABLED fault this preflight was written for, and the worst
place yet for it: an Irish filing approved after onboarding finishes would be
found by the sweep, refused at the commercial gate, and never bought.

The test below derives the required names from the source of the modules the
cron actually invokes, so a flag added later fails this until it is listed.
"""
import ast
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
CRON = (BACKEND / "scripts" / "recrawl_cron.py").read_text()

#: The modules whose run_scheduled() this cron invokes. Each owns env-name
#: constants; every one of them is read inside this process.
_LIFECYCLE_MODULES = ("temporary_numbers", "permanent_numbers", "regulatory_reconcile")

#: Read by the SIGNUP path only. Listing it on the scheduled service would
#: invite someone to set it where nothing consults it.
_WEB_ONLY = {"IRELAND_ONBOARDING_ENABLED"}


def _visible_config() -> set[str]:
    """The names the preflight prints, from the list itself."""
    tree = ast.parse(CRON)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "_VISIBLE_CONFIG" for t in node.targets)):
            return {e.value for e in node.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    raise AssertionError("_VISIBLE_CONFIG not found")


def _env_constants(module: str) -> set[str]:
    """Env var names a module defines as module-level string constants.

    Parsed, so the prose in this file naming a flag cannot satisfy it.
    """
    src = (BACKEND / "services" / f"{module}.py").read_text()
    tree = ast.parse(src)
    out = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            name = getattr(node.targets[0], "id", "")
            value = node.value.value
            if (name.endswith("_ENV") and isinstance(value, str)
                    and re.fullmatch(r"[A-Z][A-Z0-9_]+", value)):
                out.add(value)
    return out


def test_the_cron_still_runs_the_ireland_lifecycle():
    """If this stops being true the rest of the file is arguing about nothing."""
    assert "ireland_lifecycle" in CRON
    assert "run_scheduled()" in CRON
    assert "regulatory_reconcile" in CRON or "reg_rec" in CRON


@pytest.mark.parametrize("module", _LIFECYCLE_MODULES)
def test_every_flag_this_process_reads_is_printed(module):
    """Derived from the modules' own constants, so a flag added later fails
    here until someone lists it — which is the only moment anyone would think
    about setting it on both services."""
    required = _env_constants(module) - _WEB_ONLY
    assert required, f"{module} defines no env constants — has the naming changed?"
    missing = sorted(required - _visible_config())
    assert not missing, (
        f"{module} reads {missing} inside the scheduled service, but the preflight "
        f"never prints them, so nobody can tell whether they are set there")


def test_the_signup_only_flag_is_not_listed():
    """The mirror-image mistake: a flag listed on a service that never reads it
    is an invitation to set it there and believe it took effect."""
    assert not (_WEB_ONLY & _visible_config()), (
        "IRELAND_ONBOARDING_ENABLED gates signup, which this process never does")


def test_the_preflight_reports_secrets_only_as_present_or_missing():
    """Unchanged property, restated because this gate added to the list beside
    it: values are printed for config, never for secrets."""
    tree = ast.parse(CRON)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_log_env_preflight")
    src = ast.unparse(fn)
    assert "_REQUIRED_SECRETS" in src and "_VISIBLE_CONFIG" in src
    # The secret branch must not interpolate a getenv result.
    secret_half = src[:src.index("_VISIBLE_CONFIG")]
    assert "os.getenv(name" not in secret_half or "MISSING" in secret_half
