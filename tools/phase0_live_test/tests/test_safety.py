import unittest

from phase0 import safety
from phase0.safety import Guard, SafetyError


class TestNumberClass(unittest.TestCase):
    def test_emergency_rejected(self):
        for n in ("911", "112", "999", "988"):
            ok, reason = safety.number_class_ok(n)
            self.assertFalse(ok)
            self.assertEqual(reason, "emergency_number")

    def test_premium_rejected(self):
        ok, reason = safety.number_class_ok("+19005551234")
        self.assertFalse(ok)
        self.assertEqual(reason, "premium_area_code")

    def test_international_rejected(self):
        ok, reason = safety.number_class_ok("+442071838750")
        self.assertFalse(ok)
        self.assertEqual(reason, "non_domestic")

    def test_domestic_ok(self):
        ok, _ = safety.number_class_ok("+16475550123")
        self.assertTrue(ok)


class TestAllowlist(unittest.TestCase):
    def test_destination_must_be_allowlisted(self):
        with self.assertRaises(SafetyError):
            safety.assert_destination_allowed("+16475550123", ["+16475550999"])
        safety.assert_destination_allowed("+16475550123", ["+1 (647) 555-0123"])  # normalized match

    def test_unauthorized_destination_class_rejected_before_allowlist(self):
        with self.assertRaises(SafetyError):
            safety.assert_destination_allowed("911", ["911"])


class TestGuard(unittest.TestCase):
    def setUp(self):
        self.manifest = {"subaccount_sid": "ACdev", "assistant_id_m1": "asst_dev", "number": "+15550000000"}
        self.guard = Guard.from_manifest(self.manifest)

    def test_allows_manifest_targets(self):
        self.guard.assert_target_allowed("asst_dev")
        self.guard.assert_target_allowed("ACdev")

    def test_rejects_non_manifest_target(self):
        with self.assertRaises(SafetyError):
            self.guard.assert_target_allowed("asst_PRODUCTION")

    def test_deny_hash_blocks(self):
        import hashlib
        h = hashlib.sha256("prodnumber".encode()).hexdigest()
        g = Guard(frozenset({"prodnumber"}), frozenset({h}))
        with self.assertRaises(SafetyError):
            g.assert_target_allowed("prodnumber")   # deny-list wins over allow-list


class TestBudget(unittest.TestCase):
    def test_call_budget(self):
        safety.check_call_budget(19)
        with self.assertRaises(SafetyError):
            safety.check_call_budget(20)

    def test_duration(self):
        safety.check_duration(300)
        with self.assertRaises(SafetyError):
            safety.check_duration(301)


if __name__ == "__main__":
    unittest.main()
