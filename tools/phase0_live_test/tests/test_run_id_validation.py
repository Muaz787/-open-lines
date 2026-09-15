"""PHASE0_RUN_ID must be a UUID or a strong path-safe token; the webhook path is
built from the validated value."""
import unittest
import uuid

from phase0 import capture, constants as C
from phase0.safety import run_id_ok


class TestRunId(unittest.TestCase):
    def test_accepts_uuid_and_strong_token(self):
        self.assertTrue(run_id_ok(str(uuid.uuid4()))[0])
        self.assertTrue(run_id_ok("run-2026-08-02-01")[0])
        self.assertTrue(run_id_ok("A1b2C3d4")[0])

    def test_rejects_unsafe(self):
        bad = [
            "a/b", "a\\b", "..", "a..b", "with space", "q?x", "frag#x", "amp&x",
            "pct%2e", "short", "", "\x01ctrl", "a" * 65, "tab\tx", "nl\nx",
        ]
        for v in bad:
            with self.subTest(v=repr(v)):
                self.assertFalse(run_id_ok(v)[0], f"should reject {v!r}")

    def test_webhook_path_uses_validated_value(self):
        rid = "run-000042"
        self.assertTrue(run_id_ok(rid)[0])
        cfg = capture.CaptureConfig(secret="s", run_id=rid, mode=C.MODE_M1, dest="",
                                    allowlist=[], base=".", manifest={})
        self.assertEqual(cfg.webhook_path, f"{C.WEBHOOK_PATH_PREFIX}/{rid}")
        self.assertNotIn("..", cfg.webhook_path)
        self.assertEqual(cfg.webhook_path.count("/"), 2)   # /hook/<id> — no traversal


if __name__ == "__main__":
    unittest.main()
