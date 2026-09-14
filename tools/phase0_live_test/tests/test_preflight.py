"""Apply-time preflight validation (pure, no network). No --resume; area-code flow."""
import os
import tempfile
import unittest

from phase0 import preflight as PF

GOOD = {
    "PHASE0_SERVER_URL": "https://real.trycloudflare.com/hook/run-000001",
    "VAPI_SERVER_SECRET": "s", "TWILIO_ACCOUNT_SID": "AC", "TWILIO_AUTH_TOKEN": "t",
    "VAPI_API_KEY": "k", "PHASE0_AREA_CODE": "416", "PHASE0_DEST_ALLOWLIST": "+16475550123",
    "PHASE0_MODE": "warm-transfer-say-summary", "PHASE0_RUN_ID": "run-000001",
    "PHASE0_SPEND_CONTROLS_ACK": "yes", "PHASE0_DENYLIST_PEPPER": "p",
}


class TestPreflight(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()

    def test_ready_when_all_present(self):
        self.assertEqual(PF.validate(GOOD, self.base, manifest_exists=False), [])

    def test_placeholder_url_rejected(self):
        env = {**GOOD, "PHASE0_SERVER_URL": "https://TUNNEL.example/hook"}
        self.assertTrue(any("HTTPS capture URL" in p for p in PF.validate(env, self.base, manifest_exists=False)))

    def test_non_https_rejected(self):
        env = {**GOOD, "PHASE0_SERVER_URL": "http://real.tld/hook"}
        self.assertTrue(any("HTTPS" in p for p in PF.validate(env, self.base, manifest_exists=False)))

    def test_each_missing_field_flagged(self):
        for key in ("VAPI_SERVER_SECRET", "TWILIO_ACCOUNT_SID", "VAPI_API_KEY",
                    "PHASE0_DEST_ALLOWLIST", "PHASE0_RUN_ID", "PHASE0_SPEND_CONTROLS_ACK",
                    "PHASE0_DENYLIST_PEPPER"):
            env = {k: v for k, v in GOOD.items() if k != key}
            self.assertTrue(PF.validate(env, self.base, manifest_exists=False),
                            f"expected a problem when {key} missing")

    def test_area_code_required_no_explicit_number(self):
        env = {**GOOD, "PHASE0_AREA_CODE": "41"}
        self.assertTrue(any("area code" in p.lower() for p in PF.validate(env, self.base, manifest_exists=False)))
        # PHASE0_NUMBER is NOT an accepted alternative anymore
        env2 = {**GOOD, "PHASE0_AREA_CODE": "", "PHASE0_NUMBER": "+16475550123"}
        self.assertTrue(any("area code" in p.lower() for p in PF.validate(env2, self.base, manifest_exists=False)))

    def test_bad_mode(self):
        env = {**GOOD, "PHASE0_MODE": "blind-transfer"}
        self.assertTrue(any("PHASE0_MODE" in p for p in PF.validate(env, self.base, manifest_exists=False)))

    def test_existing_manifest_always_refused(self):
        problems = PF.validate(GOOD, self.base, manifest_exists=True)
        self.assertTrue(any("already exists" in p for p in problems))
        # and there is no --resume escape hatch
        self.assertTrue(all("resume" not in p.lower() or "already exists" in p for p in problems))

    def test_manifest_inside_repo_rejected(self):
        repo = tempfile.mkdtemp()
        os.makedirs(os.path.join(repo, ".git"), exist_ok=True)
        inside = os.path.join(repo, "sub")
        os.makedirs(inside, exist_ok=True)
        self.assertTrue(any("inside the repository" in p
                            for p in PF.validate(GOOD, inside, manifest_exists=False)))
        outside = tempfile.mkdtemp()
        self.assertFalse(any("inside the repository" in p
                             for p in PF.validate(GOOD, outside, manifest_exists=False)))


if __name__ == "__main__":
    unittest.main()
