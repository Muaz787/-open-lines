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
    # NOTE: httpx is intentionally NOT stubbed. It is a real installed dependency,
    # and stubbing it as a MagicMock turned httpx.HTTPStatusError / RequestError into
    # non-exception mocks, so `except httpx.HTTPStatusError` never matched (a provider
    # 400 would fall through as an opaque 500). Tests use the real httpx types.
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

# slowapi (prod-only) — provide a functional stub so importing routers that use the
# rate limiter works. .limit() is a passthrough decorator so the real endpoint
# functions (and FastAPI route registration) are preserved.
_slowapi = _types.ModuleType("slowapi")


class _Limiter:  # noqa: N801
    def __init__(self, *a, **k):
        pass

    def limit(self, *a, **k):
        def _deco(fn):
            return fn
        return _deco


_slowapi.Limiter = _Limiter  # type: ignore[attr-defined]
_slowapi_util = _types.ModuleType("slowapi.util")
_slowapi_util.get_remote_address = lambda request=None: "test"  # type: ignore[attr-defined]
_slowapi_errors = _types.ModuleType("slowapi.errors")


class RateLimitExceeded(Exception):
    pass


_slowapi_errors.RateLimitExceeded = RateLimitExceeded  # type: ignore[attr-defined]
_slowapi.util = _slowapi_util  # type: ignore[attr-defined]
_slowapi.errors = _slowapi_errors  # type: ignore[attr-defined]
sys.modules["slowapi"] = _slowapi
sys.modules["slowapi.util"] = _slowapi_util
sys.modules["slowapi.errors"] = _slowapi_errors
