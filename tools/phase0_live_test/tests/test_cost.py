"""Cost: Twilio ceil-to-minute rounding, connected vs ringing split, and actual
metered vs published estimate kept separate."""
import unittest

from phase0 import cost


class TestCost(unittest.TestCase):
    def test_twilio_ceil_to_minute(self):
        # 61s inbound -> 2 minutes (ceil), not 1.0167
        leg = {"provider": "twilio", "direction": "inbound", "seconds": 61, "state": "connected"}
        self.assertAlmostEqual(cost.estimate_leg_usd(leg), 2 * 0.0085, places=6)

    def test_vapi_per_second(self):
        leg = {"provider": "vapi", "direction": "n/a", "seconds": 30, "state": "connected"}
        self.assertAlmostEqual(cost.estimate_leg_usd(leg), (30 / 60.0) * 0.12, places=6)

    def test_connected_vs_ringing_split(self):
        legs = [
            {"provider": "twilio", "direction": "outbound", "seconds": 120, "state": "connected"},
            {"provider": "twilio", "direction": "outbound", "seconds": 20, "state": "ringing"},
        ]
        s = cost.summarize(legs)
        self.assertAlmostEqual(s["connected_minutes"], 2.0, places=3)
        self.assertAlmostEqual(s["ringing_unanswered_minutes"], 20 / 60.0, places=3)

    def test_actual_metered_separate_from_estimate(self):
        legs = [
            {"provider": "twilio", "direction": "inbound", "seconds": 60, "state": "connected", "price": -0.0085},
            {"provider": "vapi", "direction": "n/a", "seconds": 60, "state": "connected", "cost": 0.12},
        ]
        s = cost.summarize(legs)
        self.assertTrue(s["actual_metered_complete"])
        self.assertAlmostEqual(s["actual_metered_usd"], 0.1285, places=4)   # abs(price)+cost
        self.assertGreater(s["published_estimate_usd"], 0)

    def test_actual_incomplete_when_price_missing(self):
        legs = [{"provider": "twilio", "direction": "inbound", "seconds": 60, "state": "connected"}]
        s = cost.summarize(legs)
        self.assertFalse(s["actual_metered_complete"])
        self.assertIsNone(s["actual_metered_usd"])


if __name__ == "__main__":
    unittest.main()
