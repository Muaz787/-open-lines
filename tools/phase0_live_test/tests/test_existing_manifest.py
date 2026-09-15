"""An existing operational manifest ALWAYS fails closed: no overwrite, no provider
operation, and the manifest stays byte-for-byte identical."""
import hashlib
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from phase0 import cli, manifest as M, provision as PROV
from phase0.provision import ProvisionError
from phase0.providers import base as pbase

_ENV = {
    "PHASE0_SERVER_URL": "https://t.trycloudflare.com/hook/run1", "VAPI_SERVER_SECRET": "s",
    "TWILIO_ACCOUNT_SID": "AC", "TWILIO_AUTH_TOKEN": "t", "VAPI_API_KEY": "k",
    "PHASE0_AREA_CODE": "416", "PHASE0_DEST_ALLOWLIST": "+16475550123",
    "PHASE0_MODE": "warm-transfer-say-summary", "PHASE0_RUN_ID": "run1",
    "PHASE0_SPEND_CONTROLS_ACK": "yes", "PHASE0_DENYLIST_PEPPER": "p",
}


def _digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class TestExistingManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.existing = {"resource_prefix": "OL-PHASE0-DEV", "subaccount_sid": "ACprevious",
                         "suborg_api_key": "prevkey", "assistant_id_m1": "asst_prev"}
        self.path = M.write_operational(self.tmp, self.existing)
        self.before = _digest(self.path)
        pbase._TRANSPORT = lambda pr: (_ for _ in ()).throw(AssertionError("network attempted"))

    def tearDown(self):
        pbase._TRANSPORT = None

    def test_execute_refuses_and_preserves_bytes(self):
        with self.assertRaises(ProvisionError):
            PROV.execute(self.tmp, tunnel="https://t/hook", secret="s", area_code="416", run_id="run1")
        self.assertEqual(_digest(self.path), self.before)   # byte-for-byte unchanged

    def test_cli_provision_apply_refused_no_mutation(self):
        for k, v in _ENV.items():
            os.environ[k] = v
        try:
            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                rc = cli.main(["--base", self.tmp, "provision", "--apply"])
            self.assertEqual(rc, 2)
            self.assertIn("already exists", buf.getvalue())
            self.assertEqual(_digest(self.path), self.before)   # no mutation to manifest
        finally:
            for k in _ENV:
                os.environ.pop(k, None)


if __name__ == "__main__":
    unittest.main()
