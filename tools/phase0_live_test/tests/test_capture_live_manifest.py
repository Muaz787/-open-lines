"""Capture uses the CURRENT operational manifest (reloaded per request), so a
capture process started before provisioning picks up the manifest afterward
without a restart, and missing/corrupt manifests fail transfers closed."""
import json
import os
import tempfile
import unittest

from phase0 import capture, constants as C, manifest as M
from phase0.safety import SafetyError


def _cfg(base):
    return capture.CaptureConfig(secret="s", run_id="run-000001", mode=C.MODE_M1,
                                 dest="+16475550123", allowlist=["+16475550123"],
                                 base=base, manifest={})   # startup manifest empty


class TestLiveManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, C.EVIDENCE_DIR_NAME), exist_ok=True)
        self.cfg = _cfg(self.tmp)                       # (1) capture "starts" before manifest

    def _bind(self):
        M.write_operational(self.tmp, {"selected_mode": C.MODE_M1,
                                       "bound_assistant_id": "a1", "assistant_id_m1": "a1"})

    def test_1_2_health_false_before_manifest(self):
        body = capture.health_body(self.cfg)
        self.assertFalse(body["manifest_loaded"])       # (2) manifest_loaded: false
        self.assertFalse(body["mode_consistent"])

    def test_3_4_5_health_true_after_binding_no_restart(self):
        self._bind()                                    # (3) manifest created afterward
        body = capture.health_body(self.cfg)            # (4) same cfg, no restart
        self.assertTrue(body["manifest_loaded"])
        self.assertTrue(body["mode_consistent"])         # (5) mode consistency true after binding

    def test_6_transfer_only_after_consistent(self):
        with self.assertRaises(SafetyError):            # before binding -> fail closed
            capture.authorized_destination(self.cfg)
        self._bind()
        dest = capture.authorized_destination(self.cfg)  # (6) succeeds once live+consistent
        self.assertEqual(dest["destination"]["number"], "+16475550123")

    def test_7_deletion_and_corruption_fail_closed(self):
        self._bind()
        capture.authorized_destination(self.cfg)         # works
        os.remove(os.path.join(self.tmp, C.EVIDENCE_DIR_NAME, C.OPERATIONAL_MANIFEST))
        with self.assertRaises(SafetyError):             # deletion -> fail closed
            capture.authorized_destination(self.cfg)
        # corruption -> fail closed
        p = os.path.join(self.tmp, C.EVIDENCE_DIR_NAME, C.OPERATIONAL_MANIFEST)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("{ not valid json")
        self.assertEqual(capture._safe_manifest(self.tmp), {})
        with self.assertRaises(SafetyError):
            capture.authorized_destination(self.cfg)

    def test_mode_inconsistent_manifest_refused(self):
        # bound to M1 but capture configured for M2 -> refuse
        self._bind()
        cfg2 = capture.CaptureConfig(secret="s", run_id="run-000001", mode=C.MODE_M2,
                                     dest="+16475550123", allowlist=["+16475550123"],
                                     base=self.tmp, manifest={})
        with self.assertRaises(SafetyError):
            capture.authorized_destination(cfg2)


if __name__ == "__main__":
    unittest.main()
