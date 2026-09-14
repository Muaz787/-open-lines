"""SID/resource-id chaining incl. the number SEARCH + PURCHASE steps: a failure
after every creation step keeps prior ids for cleanup and stops. Driven at the
encoded-transport level (no network)."""
import json
import tempfile
import unittest

from phase0 import provision as PROV
from phase0 import manifest as M
from phase0.providers import base as pbase
from phase0.providers.base import RawResponse

# Responses in call order (7 provider calls).
_RESPONSES = [
    {"sid": "ACdev", "auth_token": "tok"},                                   # 1 subaccount
    {"id": "org_dev", "apiKey": "sk_sub"},                                   # 2 suborg
    {"id": "asst_m1"},                                                       # 3 M1
    {"id": "asst_m2"},                                                       # 4 M2
    {"available_phone_numbers": [                                            # 5 number_search
        {"phone_number": "+15550000001", "address_requirements": "none",
         "capabilities": {"voice": True}}]},
    {"sid": "PNdev", "phone_number": "+15550000001"},                        # 6 number_purchase
    {"id": "pn_dev"},                                                        # 7 import_bind
]
_KEYS_AFTER = {
    "subaccount":      ["subaccount_sid", "subaccount_auth_token"],
    "suborg":          ["suborg_id", "suborg_api_key"],
    "assistant_m1":    ["assistant_id_m1"],
    "assistant_m2":    ["assistant_id_m2"],
    "number_search":   ["number", "number_address_requirements"],
    "number_purchase": ["number_sid"],
    "import_bind":     ["vapi_phone_number_id", "bound_assistant_id"],
}


class _Transport:
    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at

    def __call__(self, prepared):
        idx = len(self.calls) + 1
        self.calls.append((prepared.method, prepared.url))
        if self.fail_at and idx == self.fail_at:
            raise RuntimeError("simulated provider failure")
        return RawResponse(200, json.dumps(_RESPONSES[idx - 1]))


class TestProvisionChaining(unittest.TestCase):
    def setUp(self):
        import os
        os.environ.update({"TWILIO_ACCOUNT_SID": "AC", "TWILIO_AUTH_TOKEN": "t", "VAPI_API_KEY": "k"})

    def tearDown(self):
        pbase._TRANSPORT = None

    def _run(self, fail_at=None):
        self.tmp = tempfile.mkdtemp()
        t = _Transport(fail_at)
        pbase._TRANSPORT = t
        res = PROV.execute(self.tmp, tunnel="https://t/hook", secret="s", area_code="416", run_id="rid1")
        return res, t

    def test_full_success(self):
        res, t = self._run()
        self.assertTrue(res.ok, res.error)
        self.assertEqual(res.completed_steps, PROV.STEP_ORDER)
        self.assertEqual(len(t.calls), 7)
        m = M.read_operational(self.tmp)
        for keys in _KEYS_AFTER.values():
            for k in keys:
                self.assertIn(k, m)
        self.assertEqual(m["bound_assistant_id"], "asst_m1")
        self.assertEqual(m["number"], "+15550000001")

    def test_failure_after_each_step(self):
        for fail_at in range(1, 8):
            with self.subTest(fail_at=fail_at):
                res, t = self._run(fail_at)
                completed = PROV.STEP_ORDER[:fail_at - 1]
                self.assertEqual(len(t.calls), fail_at)          # later steps not attempted
                self.assertFalse(res.ok)
                self.assertEqual(res.completed_steps, completed)
                self.assertEqual(res.failed_step, PROV.STEP_ORDER[fail_at - 1])
                m = M.read_operational(self.tmp)
                for step in completed:
                    for k in _KEYS_AFTER[step]:
                        self.assertIn(k, m)
                for k in _KEYS_AFTER[PROV.STEP_ORDER[fail_at - 1]]:
                    self.assertNotIn(k, m)                        # failed step's keys absent
                self.assertIsNotNone(res.cleanup)
                targets = [op.target for op in res.cleanup.operations]
                if "subaccount" in completed:
                    self.assertIn("ACdev", targets)
                if "assistant_m1" in completed:
                    self.assertIn("asst_m1", targets)
                if "number_purchase" in completed:
                    self.assertIn("PNdev", targets)               # release the purchased number

    def test_partial_manifest_not_deleted(self):
        res, _ = self._run(fail_at=3)
        self.assertIn("subaccount_sid", M.read_operational(self.tmp))


if __name__ == "__main__":
    unittest.main()
