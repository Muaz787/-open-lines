"""No provider I/O without --apply, checked at the encoded-transport level."""
import unittest

from phase0.providers import base as pbase
from phase0.providers.base import RawResponse
from phase0.providers.twilio import TwilioProvider
from phase0.providers.vapi import VapiProvider
from phase0.plan import OperationPlan


class TestNoNetworkInDryRun(unittest.TestCase):
    def setUp(self):
        import os
        os.environ.update({"TWILIO_ACCOUNT_SID": "AC", "TWILIO_AUTH_TOKEN": "t", "VAPI_API_KEY": "k"})
        self.sent = []
        pbase._TRANSPORT = lambda pr: self.sent.append((pr.method, pr.url)) or RawResponse(200, "{}")

    def tearDown(self):
        pbase._TRANSPORT = None

    def _plan(self):
        tw, vp = TwilioProvider(), VapiProvider()
        p = OperationPlan()
        p.add(tw.plan_create_subaccount("x"))
        p.add(vp.plan_create_assistant({"name": "x"}))
        p.add(vp.plan_get_assistant("asst_dev"))
        return p

    def test_dry_run_makes_zero_calls(self):
        results = self._plan().execute(apply=False)
        self.assertEqual(self.sent, [])
        self.assertTrue(all(r["status"].startswith("skipped_dry_run") for r in results))

    def test_apply_invokes_transport(self):
        self._plan().execute(apply=True)
        self.assertTrue(len(self.sent) >= 1)

    def test_building_plan_makes_no_calls(self):
        self._plan()
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
