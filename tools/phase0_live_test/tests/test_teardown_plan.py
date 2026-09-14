"""Teardown plan only targets manifest resources and is guarded."""
import unittest

from phase0.plan import OperationPlan
from phase0.providers.twilio import TwilioProvider
from phase0.providers.vapi import VapiProvider
from phase0.safety import Guard, SafetyError


class TestTeardownPlan(unittest.TestCase):
    def setUp(self):
        self.manifest = {
            "subaccount_sid": "ACdev", "number_sid": "PNdev",
            "vapi_phone_number_id": "pn_dev", "assistant_id_m1": "asst_dev",
        }
        self.guard = Guard.from_manifest(self.manifest)

    def _plan(self):
        tw, vp = TwilioProvider(), VapiProvider()
        p = OperationPlan()
        p.add(vp.plan_delete_phone_number(self.manifest["vapi_phone_number_id"]))
        p.add(tw.plan_release_number(self.manifest["subaccount_sid"], self.manifest["number_sid"]))
        p.add(vp.plan_delete_assistant(self.manifest["assistant_id_m1"]))
        return p

    def test_guard_passes_for_manifest_targets(self):
        self._plan().guard(self.guard)  # should not raise

    def test_guard_blocks_foreign_target(self):
        tw = TwilioProvider()
        p = OperationPlan()
        p.add(tw.plan_release_number("ACdev", "PN_PRODUCTION"))
        with self.assertRaises(SafetyError):
            p.guard(self.guard)

    def test_all_teardown_ops_are_mutating(self):
        self.assertTrue(all(op.mutating for op in self._plan().operations))


if __name__ == "__main__":
    unittest.main()
