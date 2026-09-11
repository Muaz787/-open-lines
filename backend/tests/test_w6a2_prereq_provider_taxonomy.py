"""
W6A2 prerequisite C1 — "gone" and "we couldn't reach Square" are different facts.

get_booking returned {} for every non-success, so a 404 and a 500 were the same
value. cancel_booking_detailed then mapped that to CANCEL_NOT_FOUND, which reads
as definitive. A transport failure on the fetch escaped entirely and the caller
mapped it to "failed" — also definitive-looking.

None of that mattered while both outcomes led to the same user-facing path. It
starts mattering the moment global mutation ownership exists, because definitive
failure RELEASES the claim and unknown must HOLD it for reconciliation. Releasing
ownership on the strength of a provider outage is how an appointment ends up
mutated by two workflows at once.

So: UNKNOWN is never collapsed into FAILED, and never into NOT_FOUND.
"""
from unittest.mock import patch

import httpx
import pytest

from services import square_booking as sb


class _Resp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is _BAD:
            raise ValueError("not json")
        return self._payload if self._payload is not None else {}


_BAD = object()          # sentinel: a body that cannot be parsed


def client(get=None, post=None, get_exc=None, post_exc=None):
    """An httpx.AsyncClient stand-in scripted per verb."""
    class _C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            if get_exc:
                raise get_exc
            return get

        async def post(self, url, **kw):
            if post_exc:
                raise post_exc
            return post

    return patch("services.square_booking.httpx.AsyncClient", _C)


BOOKING = {"id": "BK1", "status": "ACCEPTED", "location_id": "L1", "version": 3}
CANCELLED = {"id": "BK1", "status": "CANCELLED_BY_SELLER", "location_id": "L1", "version": 4}
VERSION_ERR = {"errors": [{"category": "INVALID_REQUEST_ERROR",
                           "code": "VERSION_MISMATCH", "detail": "Stale version"}]}


# ── GET: 1-6 ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_1_a_200_is_found():
    with client(get=_Resp(200, {"booking": BOOKING})):
        status, booking = await sb.get_booking_detailed("tok", "BK1")
    assert status == sb.FETCH_FOUND
    assert booking["id"] == "BK1"


@pytest.mark.asyncio
async def test_2_a_404_is_definitively_not_found():
    with client(get=_Resp(404, {}, "not found")):
        status, booking = await sb.get_booking_detailed("tok", "BK1")
    assert status == sb.FETCH_NOT_FOUND
    assert booking == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [429, 500, 502, 503])
async def test_3_and_4_rate_limits_and_server_errors_are_unknown(code):
    """A 429 is not an answer about the booking — the request may yet be served."""
    with client(get=_Resp(code, {}, "busy")):
        status, _ = await sb.get_booking_detailed("tok", "BK1")
    assert status == sb.FETCH_UNKNOWN


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [
    httpx.ReadTimeout("timed out"),
    httpx.ConnectError("refused"),
    RuntimeError("socket closed"),
])
async def test_5_and_6_transport_failures_are_unknown_not_exceptions(exc):
    """These used to escape get_booking entirely and be mapped to 'failed'."""
    with client(get_exc=exc):
        status, booking = await sb.get_booking_detailed("tok", "BK1")
    assert status == sb.FETCH_UNKNOWN
    assert booking == {}


@pytest.mark.asyncio
async def test_an_unparseable_body_is_unknown_not_found():
    with client(get=_Resp(200, _BAD)):
        status, _ = await sb.get_booking_detailed("tok", "BK1")
    assert status == sb.FETCH_UNKNOWN


@pytest.mark.asyncio
async def test_an_unexpected_4xx_is_unknown_not_absent():
    """401/403 refuse to answer ABOUT the booking; they do not say it is gone."""
    with client(get=_Resp(401, {}, "unauthorized")):
        status, _ = await sb.get_booking_detailed("tok", "BK1")
    assert status == sb.FETCH_UNKNOWN


@pytest.mark.asyncio
async def test_the_legacy_shim_still_collapses_everything_to_a_dict():
    with client(get=_Resp(200, {"booking": BOOKING})):
        assert (await sb.get_booking("tok", "BK1"))["id"] == "BK1"
    with client(get=_Resp(404, {})):
        assert await sb.get_booking("tok", "BK1") == {}
    with client(get_exc=httpx.ReadTimeout("x")):
        assert await sb.get_booking("tok", "BK1") == {}


# ── CANCEL: 7-15 ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_7_a_successful_cancel_is_ok():
    with client(get=_Resp(200, {"booking": BOOKING}), post=_Resp(200, {"booking": CANCELLED})):
        status, booking, err = await sb.cancel_booking_detailed("tok", "BK1")
    assert status == sb.CANCEL_OK
    assert "CANCELLED" in booking["status"]
    assert err == ""


@pytest.mark.asyncio
async def test_8_an_already_cancelled_booking_sends_no_request():
    """Detected before any mutation, so asking twice never cancels twice."""
    posted = []

    class _C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            return _Resp(200, {"booking": CANCELLED})

        async def post(self, url, **kw):
            posted.append(url)
            return _Resp(200, {"booking": CANCELLED})

    with patch("services.square_booking.httpx.AsyncClient", _C):
        status, _, _ = await sb.cancel_booking_detailed("tok", "BK1")
    assert status == sb.CANCEL_ALREADY
    assert posted == [], "no cancel request may be sent for a terminal booking"


@pytest.mark.asyncio
async def test_9_a_definitive_4xx_is_failed():
    with client(get=_Resp(200, {"booking": BOOKING}),
                post=_Resp(400, {"errors": [{"code": "BAD_REQUEST"}]}, "bad")):
        status, _, err = await sb.cancel_booking_detailed("tok", "BK1")
    assert status == sb.CANCEL_FAILED
    assert err == "BAD_REQUEST"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [429, 500, 503])
async def test_10_and_11_cancel_rate_limit_and_server_errors_are_unknown(code):
    """429 previously fell through to FAILED, because the test was >= 500."""
    with client(get=_Resp(200, {"booking": BOOKING}), post=_Resp(code, {}, "busy")):
        status, _, _ = await sb.cancel_booking_detailed("tok", "BK1")
    assert status == sb.CANCEL_UNKNOWN


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [httpx.ReadTimeout("t"), httpx.ConnectError("c")])
async def test_12_a_cancel_transport_failure_is_unknown(exc):
    with client(get=_Resp(200, {"booking": BOOKING}), post_exc=exc):
        status, _, _ = await sb.cancel_booking_detailed("tok", "BK1")
    assert status == sb.CANCEL_UNKNOWN


@pytest.mark.asyncio
async def test_13_a_fetch_404_is_cancel_not_found():
    with client(get=_Resp(404, {})):
        status, booking, _ = await sb.cancel_booking_detailed("tok", "BK1")
    assert status == sb.CANCEL_NOT_FOUND
    assert booking == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [429, 500, 503])
async def test_14_a_fetch_server_error_is_cancel_unknown_not_not_found(code):
    """The headline defect: this used to return CANCEL_NOT_FOUND, which a caller
    would reasonably treat as 'the booking is gone, release the claim'."""
    with client(get=_Resp(code, {}, "down")):
        status, _, _ = await sb.cancel_booking_detailed("tok", "BK1")
    assert status == sb.CANCEL_UNKNOWN
    assert status != sb.CANCEL_NOT_FOUND


@pytest.mark.asyncio
async def test_15_a_fetch_timeout_is_cancel_unknown():
    with client(get_exc=httpx.ReadTimeout("timed out")):
        status, _, _ = await sb.cancel_booking_detailed("tok", "BK1")
    assert status == sb.CANCEL_UNKNOWN


@pytest.mark.asyncio
async def test_a_2xx_with_an_unreadable_body_is_unknown_not_ok():
    """Success is probable and unproven. Unproven is what UNKNOWN is for."""
    with client(get=_Resp(200, {"booking": BOOKING}), post=_Resp(200, _BAD)):
        status, _, _ = await sb.cancel_booking_detailed("tok", "BK1")
    assert status == sb.CANCEL_UNKNOWN


def test_unknown_is_never_the_same_value_as_failed_or_not_found():
    assert len({sb.CANCEL_OK, sb.CANCEL_ALREADY, sb.CANCEL_NOT_FOUND,
                sb.CANCEL_FAILED, sb.CANCEL_UNKNOWN}) == 5


# ── 16. version mismatch ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_16_a_stale_version_is_classified_and_observable():
    """Measured against the live API: HTTP 400 with code VERSION_MISMATCH.

    W6A2 will need to recognise this structurally — after a frozen source
    fingerprint it means the MERCHANT changed the booking, which must never be
    resolved by re-fetching and cancelling the newer version. Exposing the code
    now keeps that decision off exception-string matching later.
    """
    with client(get=_Resp(200, {"booking": BOOKING}), post=_Resp(400, VERSION_ERR, "stale")):
        status, _, err = await sb.cancel_booking_detailed("tok", "BK1")
    assert status == sb.CANCEL_FAILED
    assert err == sb.ERR_VERSION_MISMATCH == "VERSION_MISMATCH"


@pytest.mark.asyncio
async def test_an_error_body_without_a_code_yields_an_empty_string_not_a_crash():
    with client(get=_Resp(200, {"booking": BOOKING}), post=_Resp(400, _BAD, "html")):
        status, _, err = await sb.cancel_booking_detailed("tok", "BK1")
    assert status == sb.CANCEL_FAILED and err == ""


@pytest.mark.asyncio
async def test_the_cancel_request_carries_the_freshly_read_version():
    """Idempotency depends on it: a stale version is rejected, the current one
    returns 200 and leaves the booking untouched."""
    sent = {}

    class _C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            return _Resp(200, {"booking": BOOKING})

        async def post(self, url, **kw):
            sent.update(kw["json"])
            return _Resp(200, {"booking": CANCELLED})

    with patch("services.square_booking.httpx.AsyncClient", _C):
        await sb.cancel_booking_detailed("tok", "BK1")
    assert sent["booking_version"] == 3
    assert "idempotency_key" in sent


# ── 17-19. W6A1 behaviour is unchanged ───────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [sb.CANCEL_FAILED, sb.CANCEL_UNKNOWN, sb.CANCEL_NOT_FOUND])
async def test_17_and_18_w6a1_writes_no_cancelled_status_for_any_non_success(outcome):
    from tests.test_w6a1_safe_cancellation import Ctx, CORK
    with Ctx(candidates=[CORK], cancel=(outcome, {})) as c:
        await c.call()
        res = await c.call(ref="appt_1")
    assert c.updates == [], "an unproven cancellation must write nothing"
    assert "remains in place" in c.text(res)


@pytest.mark.asyncio
async def test_18b_an_unreadable_provider_leaves_the_appointment_untouched():
    from tests.test_w6a1_safe_cancellation import Ctx, CORK
    with Ctx(candidates=[CORK], get_booking_error=RuntimeError("down")) as c:
        await c.call()
        res = await c.call(ref="appt_1")
    assert c.cancel_calls == [] and c.updates == []
    assert "remains in place" in c.text(res)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [sb.CANCEL_OK, sb.CANCEL_ALREADY])
async def test_19_cancelled_is_written_only_after_a_provider_confirmed_terminal_state(outcome):
    from tests.test_w6a1_safe_cancellation import Ctx, CORK
    with Ctx(candidates=[CORK], cancel=(outcome, {})) as c:
        await c.call()
        await c.call(ref="appt_1")
    assert c.cancelled_ids() == ["a-cork"]
