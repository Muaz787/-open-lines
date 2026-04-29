"""
Pre-mock all third-party packages so tests run without installing
twilio, supabase, openai, firecrawl, or pinecone.

conftest.py is loaded by pytest before any test module, so these
sys.modules entries are in place before the first import of any
services.* or db.* module.
"""
import sys
from unittest.mock import MagicMock

_STUBS = [
    "twilio",
    "twilio.rest",
    "twilio.base",
    "twilio.base.exceptions",
    "firecrawl",
    "openai",
    "pinecone",
    "supabase",
    "httpx",
]

for _mod in _STUBS:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# Ensure TwilioRestException is a real exception class so try/except works.
import types as _types
_twilio_exc = _types.ModuleType("twilio.base.exceptions")

class TwilioRestException(Exception):
    pass

_twilio_exc.TwilioRestException = TwilioRestException  # type: ignore[attr-defined]
sys.modules["twilio.base.exceptions"] = _twilio_exc
sys.modules["twilio.base"].exceptions = _twilio_exc  # type: ignore[attr-defined]
