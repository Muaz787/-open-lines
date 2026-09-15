"""Hardened capture service: auth, path/run-id, size, content-type, method, mode
consistency, sanitized persistence, and concurrent writes."""
import json
import os
import tempfile
import threading
import unittest

from phase0 import capture, constants as C

FIX = os.path.join(os.path.dirname(__file__), "..", "fixtures")
SECRET = "shh"
RUN = "run-xyz"


def _load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return json.load(fh)


def _cfg(base, mode=C.MODE_M1, dest="+16475550123"):
    manifest = {"selected_mode": mode, "bound_assistant_id": "asst_m1", "assistant_id_m1": "asst_m1"}
    return capture.CaptureConfig(secret=SECRET, run_id=RUN, mode=mode, dest=dest,
                                 allowlist=[dest], base=base, manifest=manifest)


def _headers(ct="application/json", secret=SECRET):
    h = {}
    if ct:
        h["Content-Type"] = ct
    if secret is not None:
        h[C.VAPI_SECRET_HEADER] = secret
    return h


class TestCapture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # authorized_destination reloads the manifest LIVE from disk, so write a
        # consistent operational manifest for the success-path tests.
        from phase0 import manifest as M
        M.write_operational(self.tmp, {"selected_mode": C.MODE_M1,
                                       "bound_assistant_id": "asst_m1", "assistant_id_m1": "asst_m1"})
        self.cfg = _cfg(self.tmp)
        self.writer = capture.EvidenceWriter(self.tmp)
        self.path = f"{C.WEBHOOK_PATH_PREFIX}/{RUN}"

    def _post(self, body_obj, headers=None, path=None):
        body = json.dumps(body_obj).encode() if isinstance(body_obj, dict) else body_obj
        return capture.handle_request("POST", path or self.path, headers or _headers(), body, self.cfg, self.writer)

    def test_health_has_no_secret(self):
        status, obj = capture.handle_request("GET", C.HEALTH_PATH, {}, b"", self.cfg, self.writer)
        self.assertEqual(status, 200)
        self.assertEqual(obj["status"], "ok")
        self.assertNotIn(SECRET, json.dumps(obj))

    def test_method_rejected(self):
        status, _ = capture.handle_request("PUT", self.path, _headers(), b"{}", self.cfg, self.writer)
        self.assertEqual(status, 405)

    def test_wrong_path_run_id(self):
        status, _ = self._post({"message": {"type": "x"}}, path=f"{C.WEBHOOK_PATH_PREFIX}/WRONG")
        self.assertEqual(status, 404)

    def test_wrong_content_type(self):
        status, _ = self._post({"message": {"type": "x"}}, headers=_headers(ct="text/plain"))
        self.assertEqual(status, 415)

    def test_oversized_body(self):
        big = b'{"message":{"type":"x","pad":"' + b"a" * (C.MAX_BODY_BYTES + 10) + b'"}}'
        status, _ = self._post(big)
        self.assertEqual(status, 413)

    def test_auth_missing_incorrect_correct(self):
        self.assertEqual(self._post({"message": {"type": "status-update"}}, headers=_headers(secret=None))[0], 403)
        self.assertEqual(self._post({"message": {"type": "status-update"}}, headers=_headers(secret="nope"))[0], 403)
        self.assertEqual(self._post({"message": {"type": "status-update"}})[0], 200)

    def test_dynamic_destination_is_bare_and_allowlisted(self):
        status, obj = self._post({"message": {"type": "transfer-destination-request"}})
        self.assertEqual(status, 200)
        dest = obj["destination"]
        self.assertEqual(dest["number"], "+16475550123")
        self.assertNotIn("transferPlan", dest)   # cannot alter the mode
        self.assertNotIn("mode", dest)

    def test_mode_inconsistency_refused(self):
        self.cfg = _cfg(self.tmp, mode=C.MODE_M2)   # PHASE0_MODE=M2 but manifest bound M1
        status, obj = self._post({"message": {"type": "transfer-destination-request"}})
        self.assertEqual(obj.get("error"), "no_authorized_destination")

    def test_non_allowlisted_dest_refused(self):
        self.cfg = _cfg(self.tmp, dest="+16475550199")
        self.cfg.allowlist[:] = ["+16475550123"]   # dest not in allow-list
        status, obj = self._post({"message": {"type": "transfer-destination-request"}})
        self.assertEqual(obj.get("error"), "no_authorized_destination")

    def test_persist_is_sanitized(self):
        self._post(_load("end_of_call_report_success.json"))
        d = os.path.join(self.tmp, C.EVIDENCE_DIR_NAME)
        f = [x for x in os.listdir(d) if x.startswith("events-")][0]
        with open(os.path.join(d, f), encoding="utf-8") as _fh:
            blob = _fh.read()
        self.assertIn("assistant-forwarded-call", blob)
        self.assertNotIn("SHOULD NOT BE PERSISTED", blob)
        self.assertNotIn("recordingUrl", blob)
        self.assertNotIn("6475550123", blob)

    def test_concurrent_writes(self):
        n = 40

        def worker(i):
            self.writer.write_event("end-of-call-report", {"type": "end-of-call-report",
                                                           "endedReason": f"r{i}", "durationSeconds": i})
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        with open(self.writer.path, encoding="utf-8") as _fh:
            lines = [ln for ln in _fh.read().splitlines() if ln.strip()]
        self.assertEqual(len(lines), n)              # no lost/torn writes
        for ln in lines:
            json.loads(ln)                           # every line is valid JSON


if __name__ == "__main__":
    unittest.main()
