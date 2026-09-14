import json
import unittest

from phase0 import config as CFG
from phase0 import constants as C


class TestConfig(unittest.TestCase):
    def test_no_placeholder_tokens_in_payloads(self):
        blob = json.dumps({
            "m1": CFG.dev_assistant_config(C.MODE_M1, "https://t/hook", "s"),
            "m2": CFG.dev_assistant_config(C.MODE_M2, "https://t/hook", "s"),
        })
        for bad in ("DOC?", "PLACEHOLDER", "TODO", "XXXX"):
            self.assertNotIn(bad, blob)

    def test_m1_and_m2_are_distinct_mechanisms(self):
        m1 = CFG.transfer_tool_dynamic(C.MODE_M1)["transferPlan"]
        m2 = CFG.transfer_tool_dynamic(C.MODE_M2)["transferPlan"]
        self.assertEqual(m1["mode"], "warm-transfer-say-summary")
        self.assertIn("summaryPlan", m1)
        self.assertNotIn("transferAssistant", m1)
        self.assertEqual(m2["mode"], "warm-transfer-experimental")
        self.assertIn("transferAssistant", m2)
        self.assertNotIn("summaryPlan", m2)

    def test_transfer_tool_type_and_dynamic_destinations(self):
        tool = CFG.transfer_tool_dynamic(C.MODE_M1)
        self.assertEqual(tool["type"], "transferCall")       # OpenAPI-verified camelCase
        self.assertEqual(tool["destinations"], [])           # dynamic => empty
        self.assertEqual(tool["transferPlan"]["sipVerb"], "dial")  # observable child leg
        self.assertNotIn("function", tool)                   # native tool, not a function tool

    def test_timeout_fields_present(self):
        for mode in (C.MODE_M1, C.MODE_M2):
            plan = CFG.transfer_tool_dynamic(mode)["transferPlan"]
            self.assertIn("timeout", plan)
            self.assertIn("dialTimeout", plan)

    def test_no_production_tools_present(self):
        cfg = CFG.dev_assistant_config(C.MODE_M1, "https://t/hook", "s")
        blob = json.dumps(cfg["model"]["tools"])
        for forbidden in ("book_appointment", "request_deposit", "check_availability", "caller_lookup"):
            self.assertNotIn(forbidden, blob)
        self.assertEqual(cfg["maxDurationSeconds"], C.MAX_CALL_SECONDS)

    def test_server_messages_include_transfer_and_eoc(self):
        cfg = CFG.dev_assistant_config(C.MODE_M1, "https://t/hook", "s")
        self.assertIn("transfer-destination-request", cfg["serverMessages"])
        self.assertIn("end-of-call-report", cfg["serverMessages"])

    def test_import_body_binds_assistant(self):
        body = CFG.import_number_body("+15550000000", "ACx", "asst_x", "https://t/hook", "s")
        self.assertEqual(body["assistantId"], "asst_x")
        self.assertNotIn("twilioAuthToken", body)   # secret injected at apply time only


if __name__ == "__main__":
    unittest.main()
