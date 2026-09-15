"""Secret / full-number scanner over the harness source.

- `sk_live_...` and real-looking phone numbers are flagged EVERYWHERE.
- Twilio-SID-shaped tokens (AC/PN/SK + 32 hex) are flagged only OUTSIDE tests/ and
  fixtures/, which legitimately carry fake SIDs for masking tests.
Placeholder numbers use the reserved 555-01xx range or all-zeros.
"""
import os
import re
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SID_SHAPED = re.compile(r"\b(AC|PN|SK)[0-9a-fA-F]{32}\b")
LIVE_KEY = re.compile(r"sk_live_[A-Za-z0-9]{10,}")
FULL_NANP = re.compile(r"\+1[2-9]\d{9}")

SKIP_DIRS = {"__pycache__", "phase0-evidence"}
TESTDATA_DIRS = ("/tests", "/fixtures")
ALLOWED_NUM_SUBSTR = ("5550", "5551", "0000000", "15550", "4380000000")


class TestNoSecrets(unittest.TestCase):
    def test_scan(self):
        offenders = []
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            in_testdata = any(seg in dirpath.replace(os.sep, "/") for seg in TESTDATA_DIRS)
            for fn in filenames:
                if not fn.endswith((".py", ".md", ".sh", ".json", ".env", ".example", ".txt")):
                    continue
                path = os.path.join(dirpath, fn)
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
                if LIVE_KEY.search(text):
                    offenders.append(f"{path}: live key")
                if not in_testdata and SID_SHAPED.search(text):
                    offenders.append(f"{path}: SID-shaped token")
                for m in FULL_NANP.findall(text):
                    if not any(s in m for s in ALLOWED_NUM_SUBSTR):
                        offenders.append(f"{path}: real-looking number {m[:3]}…")
        self.assertEqual(offenders, [], f"leakage: {offenders}")


if __name__ == "__main__":
    unittest.main()
