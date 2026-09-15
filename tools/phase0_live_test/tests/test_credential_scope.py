"""Vapi credential scope: parent key ONLY for sub-org creation; sub-org key for
every child resource; teardown fails safe (no parent fallback); no key leakage."""
import json
import os
import tempfile
import unittest

from phase0 import manifest as M, provision as PROV
from phase0.cleanup import build_teardown_plan
from phase0.providers import base as pbase
from phase0.providers.base import RawResponse
from phase0.providers.vapi import CredentialScopeError, vapi_for_manifest

_RESPONSES = [
    {"sid": "ACdev", "auth_token": "tok"},
    {"id": "org_dev", "apiKey": "sk_sub"},
    {"id": "asst_m1"}, {"id": "asst_m2"},
    {"available_phone_numbers": [{"phone_number": "+15550000001", "address_requirements": "none",
                                  "capabilities": {"voice": True}}]},
    {"sid": "PNdev", "phone_number": "+15550000001"},
    {"id": "pn_dev"},
]


class _AuthCapture:
    def __init__(self):
        self.auth = []

    def __call__(self, prepared):
        self.auth.append(prepared.headers.get("Authorization", ""))
        return RawResponse(200, json.dumps(_RESPONSES[len(self.auth) - 1]))


class TestScope(unittest.TestCase):
    def setUp(self):
        os.environ.update({"TWILIO_ACCOUNT_SID": "AC", "TWILIO_AUTH_TOKEN": "t", "VAPI_API_KEY": "vk_parent"})

    def tearDown(self):
        pbase._TRANSPORT = None

    def test_helper_uses_suborg_key(self):
        vp = vapi_for_manifest({"suborg_api_key": "sk_child"})
        self.assertEqual(vp.prepare("GET", "/assistant/x").headers["Authorization"], "Bearer sk_child")

    def test_helper_fails_closed_without_key(self):
        with self.assertRaises(CredentialScopeError):
            vapi_for_manifest({})

    def test_parent_only_for_suborg_creation(self):
        cap = _AuthCapture()
        pbase._TRANSPORT = cap
        tmp = tempfile.mkdtemp()
        res = PROV.execute(tmp, tunnel="https://t/hook", secret="s", area_code="416", run_id="r")
        self.assertTrue(res.ok, res.error)
        # calls: 1 twilio(subaccount, Basic), 2 vapi POST /org (PARENT Bearer vk_parent),
        #        3-4 assistants (SUB-ORG Bearer sk_sub), 5 twilio search(Basic),
        #        6 twilio purchase(Basic), 7 import (SUB-ORG Bearer sk_sub)
        self.assertEqual(cap.auth[1], "Bearer vk_parent")   # sub-org creation: parent key
        self.assertEqual(cap.auth[2], "Bearer sk_sub")      # assistant M1: sub-org key
        self.assertEqual(cap.auth[3], "Bearer sk_sub")      # assistant M2: sub-org key
        self.assertEqual(cap.auth[6], "Bearer sk_sub")      # import/bind: sub-org key
        self.assertTrue(cap.auth[0].startswith("Basic "))   # twilio subaccount

    def test_teardown_uses_suborg_key(self):
        cap = _AuthCapture()
        # canned delete responses
        cap_responses = [RawResponse(200, "{}"), RawResponse(200, "{}"), RawResponse(200, "{}"), RawResponse(200, "{}")]
        seq = iter(cap_responses)
        auth = []
        pbase._TRANSPORT = lambda pr: (auth.append(pr.headers.get("Authorization", "")), next(seq))[1]
        manifest = {"suborg_api_key": "sk_child", "assistant_id_m1": "a1",
                    "vapi_phone_number_id": "pn1", "subaccount_sid": "ACx", "number_sid": "PNx"}
        plan = build_teardown_plan(manifest)
        plan.execute(apply=True)
        # every Vapi op used the sub-org key
        vapi_auth = [a for a in auth if a.startswith("Bearer ")]
        self.assertTrue(vapi_auth)
        self.assertTrue(all(a == "Bearer sk_child" for a in vapi_auth))

    def test_teardown_fails_safe_without_key(self):
        with self.assertRaises(CredentialScopeError):
            build_teardown_plan({"assistant_id_m1": "a1"})   # vapi resource, no sub-org key

    def test_review_and_logs_never_expose_suborg_key(self):
        tmp = tempfile.mkdtemp()
        path = M.write_review(tmp, {"suborg_api_key": "sk_secret", "subaccount_auth_token": "tok",
                                    "assistant_id_m1": "asst_1"})
        with open(path, encoding="utf-8") as _fh:
            blob = _fh.read()
        self.assertNotIn("sk_secret", blob)
        self.assertNotIn("tok", blob)


if __name__ == "__main__":
    unittest.main()
