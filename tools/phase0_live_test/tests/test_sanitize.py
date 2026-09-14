import json
import os
import unittest

from phase0 import sanitize

FIX = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def _load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return json.load(fh)["message"]


class TestSanitize(unittest.TestCase):
    def test_mask_number_never_full(self):
        m = sanitize.mask_number("+16475550123")
        self.assertIn("0123", m)
        self.assertNotIn("6475550123", m)
        self.assertEqual(sanitize.mask_number(""), "«none»")

    def test_transfer_request_drops_transcript_and_headers(self):
        clean = sanitize.sanitize_event("transfer-destination-request", _load("transfer_destination_request.json"))
        blob = json.dumps(clean)
        self.assertIn("call_TESTAAA111", blob)         # id kept
        self.assertNotIn("SHOULD NOT BE PERSISTED", blob)
        self.assertNotIn("Bearer", blob)
        self.assertNotIn("6475550123", blob)           # no full number

    def test_eoc_success_keeps_reason_drops_pii(self):
        clean = sanitize.sanitize_event("end-of-call-report", _load("end_of_call_report_success.json"))
        self.assertEqual(clean["endedReason"], "assistant-forwarded-call")
        self.assertEqual(clean["durationSeconds"], 210)
        blob = json.dumps(clean)
        self.assertNotIn("SHOULD NOT BE PERSISTED", blob)
        self.assertNotIn("recordingUrl", blob)
        self.assertNotIn("example.com/rec", blob)

    def test_unknown_event_dropped(self):
        clean = sanitize.sanitize_event("conversation-update", {"transcript": "secret"})
        self.assertEqual(clean.get("note"), "unrecognized_event_dropped")
        self.assertNotIn("secret", json.dumps(clean))

    def test_mapping_masks_numbers_and_redacts_secrets(self):
        out = sanitize.sanitize_mapping({"number": "+16475550123", "api_key": "sk_live_x", "id": "ok"})
        self.assertNotIn("6475550123", json.dumps(out))
        self.assertEqual(out["api_key"], sanitize.REDACTED)
        self.assertEqual(out["id"], "ok")


if __name__ == "__main__":
    unittest.main()
