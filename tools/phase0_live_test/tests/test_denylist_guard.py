"""Mandatory production denylist: fail-closed behavior, per-type protection,
host protection, no raw-value leakage, and dry-run independence."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from phase0 import denylist as DL
from phase0 import cli
from phase0.providers import base as pbase

PEPPER = "unit-test-pepper"

# Representative production identifiers per protected type (FAKE — not real).
PROD = {
    "prod_number":      "+14380000000",
    "twilio_account":   "ACprod00000000000000000000000000",
    "twilio_subaccount":"ACsub000000000000000000000000000",
    "vapi_org":         "org_PROD",
    "vapi_assistant":   "asst_PROD",
    "vapi_phone":       "pn_PROD",
    "customer_resource":"cust_PROD_123",
}
PROD_HOST = "backend-production-71174.up.railway.app"


class TestDenylist(unittest.TestCase):
    def setUp(self):
        os.environ["PHASE0_DENYLIST_PEPPER"] = PEPPER
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "phase0-evidence"), exist_ok=True)
        self.path = DL.default_path(self.tmp)

    def tearDown(self):
        os.environ.pop("PHASE0_DENYLIST_PEPPER", None)
        pbase._HTTP_SENTINEL = None

    def _seed(self):
        DL.seed(self.path, ids=list(PROD.values()), hosts=[PROD_HOST])

    def test_every_protected_type_is_denied(self):
        self._seed()
        dl = DL.load_or_fail(self.path)
        for label, value in PROD.items():
            with self.subTest(type=label):
                self.assertTrue(dl.is_denied(value), label)
        self.assertFalse(dl.is_denied("asst_DEV_new"))   # a fresh dev id is fine

    def test_host_denied(self):
        self._seed()
        dl = DL.load_or_fail(self.path)
        self.assertTrue(dl.is_host_denied(f"https://{PROD_HOST}/webhooks/vapi-call-ended"))
        self.assertFalse(dl.is_host_denied("https://my-tunnel.trycloudflare.com/hook"))

    def test_seed_file_has_no_raw_values(self):
        self._seed()
        with open(self.path, encoding="utf-8") as fh:
            blob = fh.read()
        for value in list(PROD.values()) + [PROD_HOST]:
            self.assertNotIn(value, blob)          # only hashes stored

    def test_error_does_not_leak_raw_value(self):
        self._seed()
        dl = DL.load_or_fail(self.path)
        try:
            dl.assert_target_allowed(PROD["vapi_assistant"])
            self.fail("expected DenylistError")
        except DL.DenylistError as e:
            self.assertNotIn(PROD["vapi_assistant"], str(e))

    def test_fail_closed_missing(self):
        with self.assertRaises(DL.DenylistError):
            DL.load_or_fail(self.path)             # no file seeded

    def test_fail_closed_empty(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "algo": "hmac-sha256", "hashes": [], "host_hashes": []}, fh)
        with self.assertRaises(DL.DenylistError):
            DL.load_or_fail(self.path)

    def test_fail_closed_malformed(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        with self.assertRaises(DL.DenylistError):
            DL.load_or_fail(self.path)

    def test_fail_closed_no_pepper(self):
        self._seed()
        os.environ.pop("PHASE0_DENYLIST_PEPPER", None)
        with self.assertRaises(DL.DenylistError):
            DL.load_or_fail(self.path)


_FULL_ENV = {
    "PHASE0_SERVER_URL": "https://real-tunnel.trycloudflare.com/hook/run-123456",
    "VAPI_SERVER_SECRET": "sekret", "TWILIO_ACCOUNT_SID": "ACx", "TWILIO_AUTH_TOKEN": "tok",
    "VAPI_API_KEY": "vk", "PHASE0_AREA_CODE": "416",
    "PHASE0_DEST_ALLOWLIST": "+16475550123", "PHASE0_MODE": "warm-transfer-say-summary",
    "PHASE0_RUN_ID": "run-123456", "PHASE0_SPEND_CONTROLS_ACK": "yes",
}


class TestCliApplyGuard(unittest.TestCase):
    def setUp(self):
        os.environ["PHASE0_DENYLIST_PEPPER"] = PEPPER
        for k, v in _FULL_ENV.items():
            os.environ[k] = v
        self.tmp = tempfile.mkdtemp()   # OUTSIDE the repo
        os.makedirs(os.path.join(self.tmp, "phase0-evidence"), exist_ok=True)
        # A valid readiness receipt so provision --apply passes the receipt gate and
        # reaches the denylist gate (which must then FAIL CLOSED, no denylist file).
        from phase0 import receipt as R
        R.write(self.tmp, "run-123456", {c: True for c in R.REQUIRED_CHECKS})
        # transport raises if ANY network call is attempted
        pbase._TRANSPORT = lambda pr: (_ for _ in ()).throw(AssertionError("network attempted"))

    def tearDown(self):
        for k in list(_FULL_ENV) + ["PHASE0_DENYLIST_PEPPER"]:
            os.environ.pop(k, None)
        pbase._TRANSPORT = None

    def test_apply_fails_closed_without_denylist(self):
        # Full valid preflight env + no denylist -> preflight passes, denylist FAILS CLOSED.
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            rc = cli.main(["--base", self.tmp, "provision", "--apply"])
        self.assertEqual(rc, 2)                     # refused
        self.assertIn("fail closed", buf.getvalue().lower())

    def test_dry_run_needs_no_denylist_and_leaks_no_prod_ids(self):
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            rc = cli.main(["--base", self.tmp, "provision"])   # no --apply
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("DRY RUN", out)
        for value in list(PROD.values()) + [PROD_HOST]:
            self.assertNotIn(value, out)


if __name__ == "__main__":
    unittest.main()
