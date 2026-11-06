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
    # Email provider. Stubbing it makes services.email importable, which tests need
    # in order to patch the send_* functions by dotted name. Nothing is actually
    # delivered: services.email._send() is the single choke-point and every test
    # either patches above it or lets it no-op against this mock.
    "resend",
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

# ── the REAL twilio.request_validator, when the package is installed ─────────
# W9G verifies Twilio webhook signatures. A MagicMock validator would return a
# truthy Mock for every signature, so those tests would pass while verifying
# nothing -- the exact failure mode the tests exist to prevent. The module is pure
# stdlib (base64/hmac/hashlib/urllib), with no twilio-internal imports, so it can be
# loaded straight from its file path without disturbing the stub above.
try:  # pragma: no cover - environment dependent
    import importlib.util as _ilu
    from pathlib import Path as _Path
    for _base in sys.path:
        _cand = _Path(_base) / "twilio" / "request_validator.py"
        if _cand.is_file():
            _spec = _ilu.spec_from_file_location("twilio.request_validator", _cand)
            _rv = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_rv)
            sys.modules["twilio.request_validator"] = _rv
            sys.modules["twilio"].request_validator = _rv  # type: ignore[attr-defined]
            break
except Exception:  # the signature tests skip themselves if this did not work
    pass

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


# ── the call clock ───────────────────────────────────────────────────────────
# Tool calls now refuse dates before the call date, worked out from
# services.relative_dates._utcnow. Many fixtures book fixed dates in September and
# October 2026, so "now" is pinned before them. Tests about the clock set their own.
import pytest as _pytest
from datetime import datetime as _dt, timezone as _tz


@_pytest.fixture(autouse=True)
def _pinned_call_clock(monkeypatch):
    from services import relative_dates
    monkeypatch.setattr(relative_dates, "_utcnow", lambda: _dt(2026, 9, 1, 12, tzinfo=_tz.utc))


# ── per-call booking claims (migration 045), in memory ───────────────────────
# Same rules as the table: one row per (tenant, call, slot), one pending row per
# call, and compare-and-swap updates on state + updated_at.
import asyncio as _asyncio
import itertools as _itertools


class FakeBookingClaims:
    def __init__(self):
        self.rows: dict[tuple, dict] = {}
        self.lock = _asyncio.Lock()
        self.fail = False
        self.fail_next_transition_to = None    # e.g. "booked": that write raises, once
        self._tick = _itertools.count(1)

    def _stamp(self):
        # Real time from the service's clock (tests move it to age a claim), with a
        # microsecond tick so two writes never share a stamp.
        from datetime import timedelta as _td
        from services import booking_claims as _bc
        return (_bc._now() + _td(microseconds=next(self._tick))).isoformat()

    async def insert_pending(self, row):
        if self.fail:
            raise RuntimeError("claim store down")
        async with self.lock:
            key = (row["tenant_id"], row["vapi_call_id"], row["slot_start"])
            if key in self.rows:
                return False
            if any(r["state"] == "pending" and (r["tenant_id"], r["vapi_call_id"]) == key[:2]
                   for r in self.rows.values()):
                return False
            stamp = self._stamp()
            self.rows[key] = {**row, "state": "pending", "provider_event_id": None,
                              "appointment_id": None, "created_at": stamp, "updated_at": stamp}
            return True

    async def get(self, tenant_id, call_id, slot):
        if self.fail:
            raise RuntimeError("claim store down")
        r = self.rows.get((tenant_id, call_id, slot))
        return dict(r) if r else None

    async def pending_for_call(self, tenant_id, call_id):
        if self.fail:
            raise RuntimeError("claim store down")
        return [dict(r) for r in self.rows.values()
                if (r["tenant_id"], r["vapi_call_id"]) == (tenant_id, call_id) and r["state"] == "pending"]

    async def transition(self, claim, patch):
        if self.fail:
            raise RuntimeError("claim store down")
        if self.fail_next_transition_to and patch.get("state") == self.fail_next_transition_to:
            self.fail_next_transition_to = None
            raise RuntimeError("process died")
        async with self.lock:
            key = (claim["tenant_id"], claim["vapi_call_id"], claim["slot_start"])
            r = self.rows.get(key)
            if not r or r["state"] != claim["state"] or r["updated_at"] != claim["updated_at"]:
                return None
            if patch.get("state") == "pending" and r["state"] != "pending" and any(
                    o["state"] == "pending" and (o["tenant_id"], o["vapi_call_id"]) == key[:2]
                    for k, o in self.rows.items() if k != key):
                return None
            r.update(patch)
            r["updated_at"] = self._stamp()
            return dict(r)


@_pytest.fixture(autouse=True)
def booking_claims_store(monkeypatch):
    store = FakeBookingClaims()
    from db import booking_claims as _db_bc
    monkeypatch.setattr(_db_bc, "insert_pending", store.insert_pending)
    monkeypatch.setattr(_db_bc, "get", store.get)
    monkeypatch.setattr(_db_bc, "transition", store.transition)
    monkeypatch.setattr(_db_bc, "pending_for_call", store.pending_for_call)
    return store


# ── Google/Outlook move operations (migration 046), in memory ────────────────
class FakeCalendarMoves:
    LIVE = ("in_progress", "unknown", "provider_moved")

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.fail = False
        self._tick = _itertools.count(1)

    def _stamp(self):
        from datetime import timedelta as _td
        from services import booking_claims as _bc
        return (_bc._now() + _td(microseconds=next(self._tick))).isoformat()

    async def insert(self, row):
        if self.fail:
            raise RuntimeError("move store down")
        if any(r["appointment_id"] == row["appointment_id"] and r["state"] in self.LIVE
               for r in self.rows.values()):
            return None
        stamp = self._stamp()
        self.rows[row["id"]] = {**row, "detail": None, "created_at": stamp, "updated_at": stamp}
        return dict(self.rows[row["id"]])

    async def get(self, op_id):
        r = self.rows.get(op_id)
        return dict(r) if r else None

    async def live_for_appointment(self, appointment_id):
        if self.fail:
            raise RuntimeError("move store down")
        return next((dict(r) for r in self.rows.values()
                     if r["appointment_id"] == appointment_id and r["state"] in self.LIVE), None)

    async def transition(self, op, from_states, patch):
        r = self.rows.get(op["id"])
        if not r or r["claim_token"] != op["claim_token"] or r["state"] not in from_states:
            return None
        r.update(patch)
        r["updated_at"] = self._stamp()
        return dict(r)

    async def lease(self, op):
        r = self.rows.get(op["id"])
        if not r or r["updated_at"] != op["updated_at"] or r["state"] not in self.LIVE:
            return None
        r["updated_at"] = self._stamp()
        return dict(r)

    async def list_stale(self, before_iso, limit=20):
        return [dict(r) for r in self.rows.values()
                if r["state"] in self.LIVE and r["updated_at"] < before_iso][:limit]


@_pytest.fixture(autouse=True)
def calendar_moves_store(monkeypatch):
    store = FakeCalendarMoves()
    from db import calendar_moves as _db_cm
    for name in ("insert", "get", "live_for_appointment", "transition", "list_stale", "lease"):
        monkeypatch.setattr(_db_cm, name, getattr(store, name))
    return store


# ── #179 validation runs (migration 047), in memory ──────────────────────────
# Same rules as the table: the code hash is the key, every update is a CAS.
class FakeInplaceRuns:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.lock = _asyncio.Lock()

    async def get(self, h):
        r = self.rows.get(h)
        return dict(r) if r else None

    def arm(self, h, tenant_id):
        """What the operator's INSERT does."""
        self.rows[h] = {"code_sha256": h, "tenant_id": tenant_id, "vapi_call_id": None,
                        "appointment_id": None, "link_claimed_at": None, "payment_id": None,
                        "disabled_at": None}

    def disable_all(self):
        """What the operator's stop command does."""
        for r in self.rows.values():
            r["disabled_at"] = r["disabled_at"] or "now"

    async def use_code(self, h, tenant_id, call_id):
        async with self.lock:
            r = self.rows.get(h)
            if r and str(r["tenant_id"]) == str(tenant_id) and r["vapi_call_id"] is None \
                    and not r["disabled_at"]:
                r["vapi_call_id"] = call_id
            if (not r or str(r["tenant_id"]) != str(tenant_id) or str(r["vapi_call_id"]) != str(call_id)
                    or r["disabled_at"]):
                return None
            return dict(r)

    async def disable_unused(self, tenant_id):
        n = 0
        for r in self.rows.values():
            if str(r["tenant_id"]) == str(tenant_id) and r["vapi_call_id"] is None and not r["disabled_at"]:
                r["disabled_at"] = "burned"
                n += 1
        return n

    async def bind_appointment(self, h, appointment_id):
        async with self.lock:
            r = self.rows.get(h)
            if r and r["appointment_id"] is None and not r["disabled_at"] and not any(
                    x["appointment_id"] == appointment_id for x in self.rows.values()):
                r["appointment_id"] = appointment_id
                return True
            return False

    async def claim_link(self, h, appointment_id):
        async with self.lock:
            r = self.rows.get(h)
            if r and r["appointment_id"] == appointment_id and r["link_claimed_at"] is None \
                    and not r["disabled_at"]:
                r["link_claimed_at"] = "now"
                return True
            return False

    async def record_payment(self, h, payment_id):
        r = self.rows.get(h)
        if r and r["payment_id"] is None:
            r["payment_id"] = payment_id

    async def for_appointment(self, appointment_id):
        r = next((x for x in self.rows.values() if x["appointment_id"] == appointment_id), None)
        return dict(r) if r else None


@_pytest.fixture(autouse=True)
def inplace_runs_store(monkeypatch):
    store = FakeInplaceRuns()
    from db import inplace_test_runs as _db_runs
    for name in ("get", "use_code", "disable_unused", "bind_appointment", "claim_link", "record_payment",
                 "for_appointment"):
        monkeypatch.setattr(_db_runs, name, getattr(store, name))
    return store
