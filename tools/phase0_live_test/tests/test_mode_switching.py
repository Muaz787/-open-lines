"""M1/M2 read-back verification: ready only when requested == stored."""
import unittest

from phase0 import modeswitch as MS
from phase0 import config as CFG
from phase0 import constants as C


def _assistant_readback(mode: str, server_messages):
    return {
        "serverMessages": server_messages,
        "model": {"tools": [CFG.transfer_tool_dynamic(mode)]},
    }


GOOD_SM = ["assistant-request", "transfer-destination-request", "end-of-call-report"]


class TestModeSwitching(unittest.TestCase):
    def test_expected_mode(self):
        self.assertEqual(MS.expected_mode(C.MODE_M1), "warm-transfer-say-summary")
        self.assertEqual(MS.expected_mode(C.MODE_M2), "warm-transfer-experimental")
        with self.assertRaises(ValueError):
            MS.expected_mode("nonsense")

    def test_ready_when_all_match(self):
        ready, reasons = MS.verify_ready(
            C.MODE_M1, "asst_1",
            {"assistantId": "asst_1"},
            _assistant_readback(C.MODE_M1, GOOD_SM))
        self.assertTrue(ready, reasons)
        self.assertEqual(reasons, [])

    def test_not_ready_wrong_assistant(self):
        ready, reasons = MS.verify_ready(
            C.MODE_M1, "asst_1",
            {"assistantId": "asst_OTHER"},
            _assistant_readback(C.MODE_M1, GOOD_SM))
        self.assertFalse(ready)
        self.assertTrue(any("assistantId" in r for r in reasons))

    def test_not_ready_missing_server_message(self):
        ready, reasons = MS.verify_ready(
            C.MODE_M2, "asst_2",
            {"assistantId": "asst_2"},
            _assistant_readback(C.MODE_M2, ["assistant-request", "end-of-call-report"]))
        self.assertFalse(ready)
        self.assertTrue(any("transfer-destination-request" in r for r in reasons))

    def test_not_ready_wrong_mode(self):
        # phone bound correctly but the stored tool is M1 while we asked for M2
        ready, reasons = MS.verify_ready(
            C.MODE_M2, "asst_2",
            {"assistantId": "asst_2"},
            _assistant_readback(C.MODE_M1, GOOD_SM))
        self.assertFalse(ready)
        self.assertTrue(any("mode" in r for r in reasons))


if __name__ == "__main__":
    unittest.main()
