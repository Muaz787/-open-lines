"""Lifecycle readiness states + capture health binding."""
import tempfile
import unittest

from phase0 import lifecycle as LC
from phase0 import capture, constants as C


class TestLifecycle(unittest.TestCase):
    def test_states_progression(self):
        # nothing yet
        self.assertEqual(LC.compute_state(manifest={}, receipt_ok=False, local_ready=False, mode_consistent=False), "not_ready")
        self.assertEqual(LC.compute_state(manifest={}, receipt_ok=False, local_ready=True, mode_consistent=False), "local_preflight_ready")
        self.assertEqual(LC.compute_state(manifest={}, receipt_ok=True, local_ready=True, mode_consistent=False), "provider_preflight_ready")
        prov = {"vapi_phone_number_id": "pn"}
        self.assertEqual(LC.compute_state(manifest=prov, receipt_ok=True, local_ready=True, mode_consistent=False), "provisioned")
        mv = {"vapi_phone_number_id": "pn", "mode_verified": True}
        self.assertEqual(LC.compute_state(manifest=mv, receipt_ok=False, local_ready=True, mode_consistent=True), "mode_verified")
        self.assertEqual(LC.compute_state(manifest=mv, receipt_ok=True, local_ready=True, mode_consistent=True), "call_test_ready")
        self.assertEqual(LC.compute_state(manifest={**mv, "stopped": True}, receipt_ok=True, local_ready=True, mode_consistent=True), "stopped")
        self.assertEqual(LC.compute_state(manifest={"teardown_attempted": True}, receipt_ok=False, local_ready=False, mode_consistent=False), "teardown_incomplete")
        self.assertEqual(LC.compute_state(manifest={"teardown_verified": True}, receipt_ok=False, local_ready=False, mode_consistent=False), "teardown_verified")

    def test_guidance_blocks_calls_until_ready(self):
        for st in ("not_ready", "local_preflight_ready", "provisioned", "mode_verified"):
            self.assertIn("do NOT place", LC.guidance(st))
        self.assertIn("may place test calls", LC.guidance("call_test_ready"))

    def test_mode_verified_requires_actual_consistency(self):
        mv = {"vapi_phone_number_id": "pn", "mode_verified": True}
        # flag set but mode not consistent -> falls back to provisioned
        self.assertEqual(LC.compute_state(manifest=mv, receipt_ok=True, local_ready=True, mode_consistent=False), "provisioned")


class TestCaptureHealthBinding(unittest.TestCase):
    def _cfg(self, base, mode=C.MODE_M1, run="run-1"):
        return capture.CaptureConfig(secret="s", run_id=run, mode=mode, dest="+16475550123",
                                     allowlist=["+16475550123"], base=base, manifest={})

    def test_health_reports_run_hash_and_pre_provision_manifest_false(self):
        tmp = tempfile.mkdtemp()
        cfg = self._cfg(tmp)
        body = capture.health_body(cfg)
        self.assertEqual(body["run_id_hash"], capture.run_id_hash("run-1"))
        self.assertFalse(body["manifest_loaded"])   # pre-provision: expected, NOT call-ready
        self.assertNotIn("secret", str(body))       # health carries no secret

    def test_health_reports_manifest_loaded_after_binding(self):
        from phase0 import manifest as M
        tmp = tempfile.mkdtemp()
        M.write_operational(tmp, {"selected_mode": C.MODE_M1, "bound_assistant_id": "a1", "assistant_id_m1": "a1"})
        body = capture.health_body(self._cfg(tmp))
        self.assertTrue(body["manifest_loaded"])
        self.assertTrue(body["mode_consistent"])


if __name__ == "__main__":
    unittest.main()
