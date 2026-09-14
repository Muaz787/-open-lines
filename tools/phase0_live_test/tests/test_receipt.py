"""Receipt requires the exact minimum check set, exact booleans, ok-agreement,
valid timestamp/run-id, and owner-only permissions. Standalone ok:true not trusted."""
import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from phase0 import receipt as R

RUN = "run-000001"
FULL = {c: True for c in R.REQUIRED_CHECKS}


def _write_raw(base, payload, mode=0o600):
    d = os.path.join(base, "phase0-evidence")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, R.C.READINESS_RECEIPT)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.chmod(p, mode)
    return p


class TestReceipt(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.base, "phase0-evidence"), exist_ok=True)

    def test_missing(self):
        self.assertTrue(any("missing" in p for p in R.validate(self.base, RUN)))

    def test_valid_full_set(self):
        R.write(self.base, RUN, FULL)
        self.assertEqual(R.validate(self.base, RUN), [])

    def test_missing_required_check(self):
        partial = {k: True for k in R.REQUIRED_CHECKS if k != "twilio_read"}
        R.write(self.base, RUN, partial)
        self.assertTrue(any("twilio_read" in p for p in R.validate(self.base, RUN)))

    def test_non_boolean_value(self):
        _write_raw(self.base, {"run_id": RUN, "created_at": datetime.now(timezone.utc).isoformat(),
                               "checks": {**FULL, "twilio_read": "true"}, "ok": True})
        self.assertTrue(any("not a boolean" in p for p in R.validate(self.base, RUN)))

    def test_ok_conflicts_with_checks(self):
        # ok:true but a check is false -> must be rejected; ok alone not trusted
        _write_raw(self.base, {"run_id": RUN, "created_at": datetime.now(timezone.utc).isoformat(),
                               "checks": {**FULL, "vapi_read": False}, "ok": True})
        problems = R.validate(self.base, RUN)
        self.assertTrue(any("conflicts" in p for p in problems) or any("vapi_read' is not true" in p for p in problems))

    def test_unknown_structure(self):
        _write_raw(self.base, {"run_id": RUN, "ok": True})   # no checks dict
        self.assertTrue(any("unknown structure" in p for p in R.validate(self.base, RUN)))

    def test_wrong_run_id(self):
        R.write(self.base, RUN, FULL)
        self.assertTrue(any("different PHASE0_RUN_ID" in p for p in R.validate(self.base, "run-999999")))

    def test_stale(self):
        R.write(self.base, RUN, FULL)
        future = datetime.now(timezone.utc) + timedelta(seconds=R.C.RECEIPT_MAX_AGE_SEC + 120)
        self.assertTrue(any("stale" in p for p in R.validate(self.base, RUN, now=future)))

    def test_unsafe_permissions(self):
        _write_raw(self.base, {"run_id": RUN, "created_at": datetime.now(timezone.utc).isoformat(),
                               "checks": FULL, "ok": True}, mode=0o644)   # group/other readable
        self.assertTrue(any("permissions are unsafe" in p for p in R.validate(self.base, RUN)))

    def test_receipt_has_no_raw_payloads(self):
        path = R.write(self.base, RUN, FULL)
        with open(path, encoding="utf-8") as fh:
            blob = fh.read()
        self.assertIn("capture_health", blob)
        self.assertNotIn("Authorization", blob)
        self.assertNotIn("Bearer", blob)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
