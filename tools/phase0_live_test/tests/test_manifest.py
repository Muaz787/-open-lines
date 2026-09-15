import json
import os
import stat
import tempfile
import unittest

from phase0 import manifest as M
from phase0 import constants as C


class TestManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data = {
            "subaccount_sid": "ACdev", "number": "+16475550123",
            "twilio_auth_token": "SHOULD_NOT_APPEAR", "assistant_id_m1": "asst_dev",
        }

    def test_operational_perms_0600_and_readback(self):
        path = M.write_operational(self.tmp, self.data)
        mode = stat.S_IMODE(os.stat(path).st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual(M.read_operational(self.tmp)["assistant_id_m1"], "asst_dev")

    def test_review_manifest_has_no_secrets_or_full_numbers(self):
        path = M.write_review(self.tmp, self.data)
        with open(path, encoding="utf-8") as fh:
            blob = fh.read()
        self.assertNotIn("SHOULD_NOT_APPEAR", blob)   # token dropped
        self.assertNotIn("6475550123", blob)          # number masked
        self.assertIn("•••0123", blob)

    def test_redacted_view_never_leaks(self):
        view = json.dumps(M.redacted_view(self.data))
        self.assertNotIn("SHOULD_NOT_APPEAR", view)
        self.assertNotIn("6475550123", view)

    def test_delete_operational(self):
        M.write_operational(self.tmp, self.data)
        self.assertTrue(M.delete_operational(self.tmp))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, C.EVIDENCE_DIR_NAME, C.OPERATIONAL_MANIFEST)))


if __name__ == "__main__":
    unittest.main()
