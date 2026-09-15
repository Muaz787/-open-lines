"""Live-preflight plan is read-only (GET only) and includes a real Twilio read."""
import os
import tempfile
import unittest

from phase0 import cli


class TestLivePreflightPlan(unittest.TestCase):
    def setUp(self):
        os.environ["TWILIO_ACCOUNT_SID"] = "ACmaster"

    def test_includes_twilio_read(self):
        plan = cli.build_live_preflight_plan(tempfile.mkdtemp())
        actions = [(op.provider, op.action) for op in plan.operations]
        self.assertIn(("twilio", "get_account"), actions)
        self.assertIn(("vapi", "list_assistants"), actions)

    def test_all_ops_are_get_and_non_mutating(self):
        plan = cli.build_live_preflight_plan(tempfile.mkdtemp())
        for op in plan.operations:
            self.assertEqual(op.method, "GET", f"{op.action} must be GET")
            self.assertFalse(op.mutating, f"{op.action} must be non-mutating")


if __name__ == "__main__":
    unittest.main()
