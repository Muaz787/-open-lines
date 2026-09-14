"""select-mode performs EXACTLY: one binding PATCH, one phone-number GET, one
assistant GET (no duplicate phone read)."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from phase0 import cli, config as CFG, constants as C, denylist as DL, manifest as M
from phase0.providers import base as pbase
from phase0.providers.base import RawResponse

GOOD_SM = ["assistant-request", "transfer-destination-request", "end-of-call-report"]


class _Seq:
    def __init__(self):
        self.calls = []      # (method, url)
        self.responses = [
            RawResponse(200, "{}"),                                   # 1 PATCH bind
            RawResponse(200, json.dumps({"assistantId": "a1"})),      # 2 GET phone-number
            RawResponse(200, json.dumps({"serverMessages": GOOD_SM,   # 3 GET assistant
                                         "model": {"tools": [CFG.transfer_tool_dynamic(C.MODE_M1)]}})),
        ]

    def __call__(self, prepared):
        self.calls.append((prepared.method, prepared.url))
        return self.responses[len(self.calls) - 1]


class TestSelectModeOps(unittest.TestCase):
    def setUp(self):
        os.environ["PHASE0_DENYLIST_PEPPER"] = "pepper"
        os.environ["VAPI_API_KEY"] = "vk"
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "phase0-evidence"), exist_ok=True)
        DL.seed(DL.default_path(self.tmp), ids=[], hosts=["some-prod-host.example"])  # valid, non-empty
        M.write_operational(self.tmp, {"resource_prefix": "OL-PHASE0-DEV", "selected_mode": C.MODE_M1,
                                       "suborg_api_key": "sk_child", "vapi_phone_number_id": "pn1",
                                       "assistant_id_m1": "a1"})

    def tearDown(self):
        pbase._TRANSPORT = None
        for k in ("PHASE0_DENYLIST_PEPPER", "VAPI_API_KEY"):
            os.environ.pop(k, None)

    def test_exactly_one_patch_one_phone_get_one_assistant_get(self):
        seq = _Seq()
        pbase._TRANSPORT = seq
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            rc = cli.main(["--base", self.tmp, "select-mode", "--mode", "M1", "--apply"])
        self.assertEqual(rc, 0, buf.getvalue())
        methods = [m for m, _ in seq.calls]
        self.assertEqual(methods, ["PATCH", "GET", "GET"])          # exactly 3 ops
        phone_gets = [u for m, u in seq.calls if m == "GET" and "/phone-number/" in u]
        self.assertEqual(len(phone_gets), 1)                        # no duplicate phone read
        # mode_verified recorded on success
        self.assertTrue(M.read_operational(self.tmp).get("mode_verified"))


if __name__ == "__main__":
    unittest.main()
