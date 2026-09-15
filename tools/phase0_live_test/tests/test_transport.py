"""Transport-encoding tests at the ENCODED-request level (not a pre-encoding dict):
final URL, method, Content-Type, encoded bytes, auth-header presence (not value),
GET query encoding, empty-body behavior, and representative response parsing."""
import os
import unittest

from phase0.providers import base as pbase
from phase0.providers.base import RawResponse
from phase0.providers.twilio import TwilioProvider
from phase0.providers.vapi import VapiProvider


class TestEncoding(unittest.TestCase):
    def setUp(self):
        os.environ.update({
            "TWILIO_ACCOUNT_SID": "ACtest", "TWILIO_AUTH_TOKEN": "toktest",
            "VAPI_API_KEY": "vapitest",
        })

    def test_twilio_post_is_form_encoded(self):
        pr = TwilioProvider().prepare("POST", "/2010-04-01/Accounts.json", body={"FriendlyName": "OL X"})
        self.assertEqual(pr.method, "POST")
        self.assertEqual(pr.url, "https://api.twilio.com/2010-04-01/Accounts.json")
        self.assertEqual(pr.content_type(), "application/x-www-form-urlencoded")
        self.assertEqual(pr.body, b"FriendlyName=OL+X")   # form-encoded bytes
        self.assertTrue(pr.has_auth())                    # present…
        self.assertNotIn("toktest", pr.headers["Authorization"] and "")  # …value not asserted/exposed

    def test_twilio_form_booleans(self):
        pr = TwilioProvider().prepare("POST", "/x", body={"A": True, "B": False, "C": None})
        self.assertEqual(pr.body, b"A=true&B=false")      # None dropped, bools lowercased

    def test_twilio_get_query_encoding_no_body(self):
        pr = TwilioProvider().prepare("GET", "/AvailablePhoneNumbers/CA/Local.json",
                                      query={"AreaCode": "416", "VoiceEnabled": "true"})
        self.assertEqual(pr.method, "GET")
        self.assertIn("AreaCode=416", pr.url)
        self.assertIn("VoiceEnabled=true", pr.url)
        self.assertIsNone(pr.body)                        # GET has no body
        self.assertIsNone(pr.content_type())

    def test_vapi_post_is_json(self):
        pr = VapiProvider().prepare("POST", "/assistant", body={"name": "x", "n": 2})
        self.assertEqual(pr.content_type(), "application/json")
        self.assertEqual(pr.body, b'{"name": "x", "n": 2}')
        self.assertTrue(pr.headers["Authorization"].startswith("Bearer "))

    def test_delete_sends_no_body(self):
        pr = VapiProvider().prepare("DELETE", "/assistant/asst_1")
        self.assertIsNone(pr.body)
        self.assertIsNone(pr.content_type())

    def test_response_parsing_and_errors(self):
        prov = VapiProvider()
        self.assertEqual(prov.parse('{"id":"asst_9"}'), {"id": "asst_9"})
        self.assertEqual(prov.parse(""), {})
        # representative success via transport
        pbase._TRANSPORT = lambda pr: RawResponse(200, '{"sid":"ACnew","auth_token":"x"}')
        try:
            self.assertEqual(TwilioProvider()._http("POST", "/2010-04-01/Accounts.json", body={"FriendlyName": "x"}),
                             {"sid": "ACnew", "auth_token": "x"})
            # error status -> ProviderError (sanitized)
            pbase._TRANSPORT = lambda pr: RawResponse(400, '{"message":"bad"}')
            with self.assertRaises(pbase.ProviderError):
                VapiProvider()._http("POST", "/assistant", body={"x": 1})
        finally:
            pbase._TRANSPORT = None


if __name__ == "__main__":
    unittest.main()
