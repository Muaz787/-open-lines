"""Live-preflight loads the mandatory denylist and refuses a production capture
host BEFORE contacting anything — zero network requests on refusal."""
import io
import os
import tempfile
import unittest
import urllib.request
from contextlib import redirect_stdout, redirect_stderr

from phase0 import cli, denylist as DL
from phase0.providers import base as pbase

HOST = "backend-production-71174.up.railway.app"


class TestHostRefusal(unittest.TestCase):
    def setUp(self):
        os.environ["PHASE0_DENYLIST_PEPPER"] = "pepper"
        os.environ["PHASE0_SERVER_URL"] = f"https://{HOST}/hook/run-000001"
        os.environ["PHASE0_RUN_ID"] = "run-000001"
        os.environ["TWILIO_ACCOUNT_SID"] = "ACx"
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "phase0-evidence"), exist_ok=True)
        DL.seed(DL.default_path(self.tmp), ids=[], hosts=[HOST])   # deny the prod host
        # Record any network attempt (provider transport + urllib).
        self.net = []
        pbase._TRANSPORT = lambda pr: self.net.append(("provider", pr.url)) or None
        self._orig = urllib.request.urlopen
        urllib.request.urlopen = lambda *a, **k: self.net.append(("urlopen", a[0] if a else "")) or (_ for _ in ()).throw(AssertionError("network"))

    def tearDown(self):
        urllib.request.urlopen = self._orig
        pbase._TRANSPORT = None
        for k in ("PHASE0_DENYLIST_PEPPER", "PHASE0_SERVER_URL", "PHASE0_RUN_ID", "TWILIO_ACCOUNT_SID"):
            os.environ.pop(k, None)

    def test_denied_host_refused_zero_network(self):
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            rc = cli.main(["--base", self.tmp, "preflight-live", "--apply"])
        self.assertEqual(rc, 2)
        self.assertIn("REFUSED", buf.getvalue())
        self.assertEqual(self.net, [])          # no host contacted, no provider read

    def test_missing_denylist_refused(self):
        os.remove(DL.default_path(self.tmp))    # denylist gone -> fail closed
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            rc = cli.main(["--base", self.tmp, "preflight-live", "--apply"])
        self.assertEqual(rc, 2)
        self.assertEqual(self.net, [])


if __name__ == "__main__":
    unittest.main()
