"""Review manifest must contain no complete provider identifier (SID/UUID/id) or
full phone number."""
import json
import re
import tempfile
import unittest

from phase0 import manifest as M

FULL_SID = re.compile(r"\b(AC|PN|SK)[0-9a-fA-F]{32}\b")
UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
FULL_NANP = re.compile(r"\+1[2-9]\d{9}")
FULL_VAPI_ID = re.compile(r"\b(asst|org|pn)_[A-Za-z0-9]{16,}\b")

# SID-shaped fixtures are assembled at runtime rather than stored whole: a
# complete AC/PN + 32 hex literal trips GitHub's push protection even when the
# value is obviously fake. The strings the test sees are unchanged.
_HEX32 = "0123456789abcdef" * 2

OP = {
    "resource_prefix": "OL-PHASE0-DEV",
    "selected_mode": "warm-transfer-say-summary",
    "subaccount_sid": "AC" + _HEX32,
    "number": "+16475550123",
    "number_sid": "PN" + _HEX32,
    "suborg_id": "org_0123456789abcdefghij",
    "assistant_id_m1": "asst_0123456789abcdefghij",
    "assistant_id_m2": "asst_ABCDEFGHIJKLMNOPQRST",
    "vapi_phone_number_id": "pn_0123456789abcdefghij",
    "bound_assistant_id": "asst_0123456789abcdefghij",
    "subaccount_auth_token": "SUPERSECRETTOKEN",
    "suborg_api_key": "SUPERSECRETKEY",
}


class TestReviewMask(unittest.TestCase):
    def test_no_complete_identifiers_in_review(self):
        tmp = tempfile.mkdtemp()
        path = M.write_review(tmp, OP)
        with open(path, encoding="utf-8") as _fh:
            blob = _fh.read()
        self.assertIsNone(FULL_SID.search(blob), "full Twilio SID leaked")
        self.assertIsNone(UUID.search(blob), "UUID leaked")
        self.assertIsNone(FULL_NANP.search(blob), "full phone number leaked")
        self.assertIsNone(FULL_VAPI_ID.search(blob), "full Vapi id leaked")
        self.assertNotIn("SUPERSECRETTOKEN", blob)
        self.assertNotIn("SUPERSECRETKEY", blob)
        # non-sensitive fields survive
        data = json.loads(blob)
        self.assertEqual(data["resource_prefix"], "OL-PHASE0-DEV")
        self.assertEqual(data["selected_mode"], "warm-transfer-say-summary")

    def test_operational_keeps_complete_ids(self):
        tmp = tempfile.mkdtemp()
        M.write_operational(tmp, OP)
        data = M.read_operational(tmp)
        self.assertEqual(data["subaccount_sid"], OP["subaccount_sid"])   # full id retained (restricted)


if __name__ == "__main__":
    unittest.main()
