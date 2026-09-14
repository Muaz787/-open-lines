"""Partial-failure recovery: a failing op stops the plan and reports progress."""
import unittest

from phase0.plan import OperationPlan, PlannedOperation


class TestPartialFailure(unittest.TestCase):
    def test_stops_and_reports(self):
        ran = []
        p = OperationPlan()
        p.add(PlannedOperation("vapi", "op_a", "DELETE", "asst_a", True, _run=lambda: ran.append("a") or {}))
        p.add(PlannedOperation("vapi", "op_b", "DELETE", "asst_b", True,
                               _run=lambda: (_ for _ in ()).throw(RuntimeError("boom"))))
        p.add(PlannedOperation("vapi", "op_c", "DELETE", "asst_c", True, _run=lambda: ran.append("c") or {}))
        results = p.execute(apply=True)
        self.assertEqual(ran, ["a"])                       # c never ran
        self.assertTrue(any(r.get("_partial_failure") for r in results))
        self.assertTrue(any(r.get("status") == "error" for r in results))


if __name__ == "__main__":
    unittest.main()
