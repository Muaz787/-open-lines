"""W7T — the Supabase HTTP transport policy.

W7D failed in production with `RemoteProtocolError: <ConnectionTerminated
error_code:0>` on every Square webhook delivery: a graceful HTTP/2 GOAWAY on a
long-lived pooled connection, which httpx surfaces as a request failure instead
of renewing the connection. These tests pin the behaviour that makes that
unreachable, and -- just as importantly -- pin the two reconstruction paths that
would silently undo it.
"""
import importlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

import httpx
import pytest

from db import supabase_transport as T


@pytest.fixture(autouse=True)
def _fresh_policy(monkeypatch):
    """Each test starts from an uninstalled policy and a clean env.

    install() rebinds names inside postgrest/gotrue for the whole process, so
    without this the first test to run would decide what every later test sees.
    """
    for var in (
        "SUPABASE_HTTP2",
        "SUPABASE_HTTP_CONNECT_TIMEOUT", "SUPABASE_HTTP_READ_TIMEOUT",
        "SUPABASE_HTTP_WRITE_TIMEOUT", "SUPABASE_HTTP_POOL_TIMEOUT",
        "SUPABASE_HTTP_MAX_CONNECTIONS", "SUPABASE_HTTP_MAX_KEEPALIVE",
        "SUPABASE_HTTP_KEEPALIVE_EXPIRY",
    ):
        monkeypatch.delenv(var, raising=False)

    import gotrue._sync.gotrue_base_api as gt
    import postgrest._sync.client as pg

    # install() rebinds these names for the whole PROCESS, and any earlier test
    # module that reaches a real get_client() will have triggered it. Capturing
    # `module.SyncClient` as-is therefore captures the FACTORY, not the library
    # class — and the fixture would then "restore" the factory, so the next
    # install() saw its own work and reported already-patched instead of the
    # module path.
    #
    # That is why three of these tests failed when this file ran after
    # test_w7a/w7b/w7d while passing on their own and in the full suite: the
    # outcome depended on which module happened to touch the client first.
    #
    # So: unwrap to the library class and rebind it BEFORE the test body, and
    # put back whatever was actually there afterwards.
    restore, originals = [], []
    for module in (pg, gt):
        current = module.SyncClient
        original = getattr(current, "wrapped_cls", current)
        restore.append((module, "SyncClient", current))
        originals.append((module, "SyncClient", original))
        setattr(module, "SyncClient", original)

    saved = (T._installed, dict(T._patched))
    T._installed = False
    T._patched.clear()
    yield
    for module, attr, value in restore:
        setattr(module, attr, value)
    T._installed, patched = saved[0], saved[1]
    T._patched.clear()
    T._patched.update(patched)


# ---------------------------------------------------------------------------
# The policy values themselves
# ---------------------------------------------------------------------------

def test_http2_is_off_by_default():
    """The entire point of W7T. If this ever flips, W7D's failure returns."""
    assert T.http2_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_http2_escape_hatch_is_opt_in_only(monkeypatch, value):
    """HTTP/1.1 can be reversed by env, so an incident does not need a rollback."""
    monkeypatch.setenv("SUPABASE_HTTP2", value)
    assert T.http2_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "   ", "maybe"])
def test_anything_not_clearly_true_leaves_http2_off(monkeypatch, value):
    monkeypatch.setenv("SUPABASE_HTTP2", value)
    assert T.http2_enabled() is False


def test_default_timeout_is_componentwise_not_postgrests_flat_120():
    """postgrest's default is a flat 120s on every phase, so a hung connect
    blocks a webhook handler for two minutes while Square retries on top."""
    t = T.build_timeout()
    assert (t.connect, t.read, t.write, t.pool) == (5.0, 30.0, 30.0, 5.0)
    assert t.connect != 120 and t.read != 120


def test_default_keepalive_expiry_is_shorter_than_a_server_idle_timeout():
    """We must retire an idle socket before the other end does. httpx's own
    default is 5s, which is safe but wasteful; anything above ~60s is not."""
    limits = T.build_limits()
    assert limits.keepalive_expiry == 30.0
    assert 0 < limits.keepalive_expiry < 60


def test_default_limits_are_bounded():
    limits = T.build_limits()
    assert limits.max_connections == 20
    assert limits.max_keepalive_connections == 10


def test_every_knob_is_overridable_by_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_HTTP_CONNECT_TIMEOUT", "2.5")
    monkeypatch.setenv("SUPABASE_HTTP_READ_TIMEOUT", "7")
    monkeypatch.setenv("SUPABASE_HTTP_WRITE_TIMEOUT", "8")
    monkeypatch.setenv("SUPABASE_HTTP_POOL_TIMEOUT", "9")
    monkeypatch.setenv("SUPABASE_HTTP_MAX_CONNECTIONS", "4")
    monkeypatch.setenv("SUPABASE_HTTP_MAX_KEEPALIVE", "3")
    monkeypatch.setenv("SUPABASE_HTTP_KEEPALIVE_EXPIRY", "11")
    t, limits = T.build_timeout(), T.build_limits()
    assert (t.connect, t.read, t.write, t.pool) == (2.5, 7.0, 8.0, 9.0)
    assert (limits.max_connections, limits.max_keepalive_connections) == (4, 3)
    assert limits.keepalive_expiry == 11.0


@pytest.mark.parametrize("bad", ["abc", "0", "-5", "1e", "None"])
def test_a_bad_env_value_falls_back_to_the_tested_default(monkeypatch, bad):
    """A typo in a Railway variable must not produce an untested pool. Falling
    back loudly beats a 0-second timeout that fails every request."""
    monkeypatch.setenv("SUPABASE_HTTP_CONNECT_TIMEOUT", bad)
    monkeypatch.setenv("SUPABASE_HTTP_MAX_CONNECTIONS", bad)
    assert T.build_timeout().connect == T.DEFAULT_CONNECT_TIMEOUT
    assert T.build_limits().max_connections == T.DEFAULT_MAX_CONNECTIONS


def test_keepalive_ceiling_is_clamped_to_the_connection_ceiling(monkeypatch):
    monkeypatch.setenv("SUPABASE_HTTP_MAX_CONNECTIONS", "5")
    monkeypatch.setenv("SUPABASE_HTTP_MAX_KEEPALIVE", "50")
    limits = T.build_limits()
    assert limits.max_keepalive_connections == 5


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------

def test_install_patches_both_construction_sites():
    result = T.install()
    assert result == {
        "postgrest": "postgrest._sync.client.SyncClient",
        "gotrue": "gotrue._sync.gotrue_base_api.SyncClient",
    }


def test_install_is_idempotent():
    first = T.install()
    import postgrest._sync.client as pg
    factory = pg.SyncClient
    assert T.install() == first
    assert pg.SyncClient is factory, "a second install() must not wrap the wrapper"


def test_install_does_not_double_wrap_across_a_reset():
    """Belt and braces: even if the _installed flag is lost (a module reload,
    a test fixture), the component tag on the factory stops a second layer."""
    T.install()
    T._installed = False
    T.install()
    import postgrest._sync.client as pg
    assert pg.SyncClient.wrapped_cls.__module__.startswith("postgrest")


def test_install_fails_open_when_a_library_moves_the_name(monkeypatch):
    """A postgrest refactor must degrade us to the old transport, never take
    the API down. The diagnostic then reports the component as FAILED."""
    import postgrest._sync.client as pg
    monkeypatch.delattr(pg, "SyncClient")
    result = T.install()
    assert result["postgrest"].startswith("FAILED")
    assert result["gotrue"] == "gotrue._sync.gotrue_base_api.SyncClient"


def test_the_factory_constructs_the_librarys_own_class_not_a_bare_httpx_client():
    """postgrest and gotrue both call session.aclose() on shutdown, which only
    their httpx.Client subclasses have. Returning httpx.Client would break
    every close path."""
    import postgrest._sync.client as pg
    original = pg.SyncClient
    T.install()
    session = pg.SyncClient(base_url="https://example.invalid", headers={}, timeout=1)
    assert isinstance(session, original)
    assert hasattr(session, "aclose")
    session.close()


def test_the_factory_overrides_http2_even_when_the_caller_demands_it():
    """postgrest passes http2=True explicitly and unconditionally. The policy
    has to win over the argument, not merely supply a default."""
    import postgrest._sync.client as pg
    T.install()
    session = pg.SyncClient(base_url="https://example.invalid", headers={}, timeout=1, http2=True)
    assert T.session_http2_enabled(session) is False
    session.close()


def test_the_factory_replaces_the_callers_timeout_and_adds_limits():
    import postgrest._sync.client as pg
    T.install()
    session = pg.SyncClient(base_url="https://example.invalid", headers={}, timeout=120)
    assert session.timeout.connect == 5.0
    assert session._transport._pool._keepalive_expiry == 30.0
    assert session._transport._pool._max_connections == 20
    session.close()


def test_the_factory_preserves_base_url_and_headers():
    """The session still has to work: identity and routing come from the
    caller, only transport comes from us."""
    import postgrest._sync.client as pg
    T.install()
    session = pg.SyncClient(
        base_url="https://example.invalid/rest/v1",
        headers={"Accept-Profile": "public"},
        timeout=1,
    )
    # httpx normalises a base_url to a trailing slash; the host and path are ours.
    assert str(session.base_url) == "https://example.invalid/rest/v1/"
    assert session.headers["accept-profile"] == "public"
    session.close()


def test_the_escape_hatch_reaches_the_constructed_session(monkeypatch):
    monkeypatch.setenv("SUPABASE_HTTP2", "1")
    import postgrest._sync.client as pg
    T.install()
    session = pg.SyncClient(base_url="https://example.invalid", headers={}, timeout=1)
    assert T.session_http2_enabled(session) is True
    session.close()


# ---------------------------------------------------------------------------
# The two paths that would silently rebuild an HTTP/2 session
# ---------------------------------------------------------------------------

def test_a_directly_constructed_postgrest_client_is_hardened():
    """This is the path supabase.Client.postgrest takes. It matters beyond
    first boot: _listen_to_auth_events sets _postgrest = None on SIGNED_IN /
    TOKEN_REFRESHED / SIGNED_OUT, and the property then rebuilds from here.
    A post-construction session swap would not survive that; patching the
    constructor does."""
    from postgrest import SyncPostgrestClient
    T.install()
    client = SyncPostgrestClient("https://example.invalid/rest/v1")
    assert T.session_http2_enabled(client.session) is False
    assert client.session.timeout.connect == 5.0
    client.aclose()


def test_the_schema_derived_client_is_hardened_too():
    """SyncPostgrestClient.schema() constructs a whole new client rather than
    reusing the session, so it is a second way back to HTTP/2."""
    from postgrest import SyncPostgrestClient
    T.install()
    client = SyncPostgrestClient("https://example.invalid/rest/v1")
    derived = client.schema("other")
    assert T.session_http2_enabled(derived.session) is False
    client.aclose()
    derived.aclose()


def test_the_gotrue_client_is_hardened():
    """services/security.py calls auth.get_user() on every authenticated
    dashboard request, over gotrue's own long-lived HTTP/2 client."""
    from gotrue._sync.gotrue_base_api import SyncGoTrueBaseAPI
    T.install()
    api = SyncGoTrueBaseAPI(url="https://example.invalid", headers={}, http_client=None)
    assert T.session_http2_enabled(api._http_client) is False
    api.close()


# ---------------------------------------------------------------------------
# Reading the real protocol back
# ---------------------------------------------------------------------------

def test_session_http2_enabled_reads_httpcore_not_our_own_argument():
    """The startup assertion exists to catch the case where the policy did not
    take. A value we wrote ourselves could not catch that, so it is read from
    the connection pool."""
    off = httpx.Client(http2=False)
    on = httpx.Client(http2=True)
    assert T.session_http2_enabled(off) is False
    assert T.session_http2_enabled(on) is True
    off.close()
    on.close()


def test_an_unrecognisable_session_reads_as_unknown_never_as_a_pass():
    """If httpcore restructures, the diagnostic must say "I don't know",
    because a silent False would claim a mitigation we cannot see."""
    assert T.session_http2_enabled(object()) is None
    assert T.session_http2_enabled(MagicMock()) is None


# ---------------------------------------------------------------------------
# Diagnostic
# ---------------------------------------------------------------------------

def _fake_supabase_client():
    client = MagicMock()
    client.postgrest.session = httpx.Client(
        base_url="https://tenant.supabase.co/rest/v1",
        headers={"Authorization": "Bearer super-secret-service-role-key",
                 "apiKey": "super-secret-service-role-key"},
        http2=False,
    )
    client.auth._http_client = httpx.Client(http2=False)
    return client


def test_the_diagnostic_leaks_no_url_key_or_header():
    """It is logged on every boot, so it has to be safe by construction."""
    client = _fake_supabase_client()
    blob = json.dumps(T.describe(client), default=str)
    for secret in ("super-secret-service-role-key", "tenant.supabase.co",
                   "Bearer", "apiKey", "Authorization"):
        assert secret not in blob, f"{secret!r} leaked into the transport diagnostic"
    client.postgrest.session.close()
    client.auth._http_client.close()


def test_the_diagnostic_reports_protocol_pool_and_versions():
    client = _fake_supabase_client()
    info = T.describe(client)
    assert info["policy_http2"] is False
    assert info["sessions"]["postgrest"]["http2"] is False
    assert info["sessions"]["auth"]["http2"] is False
    assert info["limits"]["keepalive_expiry"] == 30.0
    assert info["versions"]["postgrest"] == "1.0.2"
    client.postgrest.session.close()
    client.auth._http_client.close()


def test_assert_hardened_logs_an_error_when_the_policy_did_not_take(caplog):
    """The one thing this must not do is pass quietly while the process is
    running the configuration that caused the outage."""
    client = MagicMock()
    client.postgrest.session = httpx.Client(http2=True)
    client.auth._http_client = httpx.Client(http2=False)
    with caplog.at_level("ERROR"):
        T.assert_hardened(client)
    assert any("NOT mitigated" in r.message for r in caplog.records)
    client.postgrest.session.close()
    client.auth._http_client.close()


def test_assert_hardened_never_raises():
    """A backend that refuses to boot is strictly worse than a backend on the
    transport it has been running on all along."""
    broken = MagicMock()
    broken.postgrest = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
    assert isinstance(T.assert_hardened(broken), dict)


def test_version_drift_is_logged(caplog, monkeypatch):
    """postgrest, gotrue, httpcore and h2 were unpinned before W7T. If a build
    ever ships a different stack, the deploy log has to say so."""
    monkeypatch.setattr(T, "TESTED_VERSIONS", {"httpx": "0.0.0-not-real"})
    with caplog.at_level("WARNING"):
        T._log_version_drift()
    assert any("dependency drift" in r.message for r in caplog.records)


def test_no_drift_against_the_installed_stack():
    """The pins in requirements.txt and TESTED_VERSIONS must not disagree."""
    assert T.installed_versions() == T.TESTED_VERSIONS


def test_requirements_pins_the_whole_transport_stack():
    import pathlib
    text = pathlib.Path(__file__).resolve().parents[1].joinpath("requirements.txt").read_text()
    for line in ("httpx==0.27.2", "supabase==2.15.0", "postgrest==1.0.2",
                 "gotrue==2.12.4", "httpcore==1.0.9", "h2==4.3.0"):
        assert line in text, f"{line} is not pinned; a rebuild could change the transport"


# ---------------------------------------------------------------------------
# Client lifecycle and concurrency
# ---------------------------------------------------------------------------

@pytest.fixture
def db_module():
    import db.supabase as db
    saved = db._client
    db._client = None
    yield db
    db._client = saved


def test_the_policy_is_installed_before_the_client_is_constructed(db_module, monkeypatch):
    """Ordering is the whole mechanism: the policy replaces the constructor
    each sub-client calls, so a client built first keeps HTTP/2 forever."""
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "key")
    order = []
    with patch.object(T, "install", side_effect=lambda: order.append("install") or {}), \
         patch.object(db_module, "create_client",
                      side_effect=lambda *a, **k: order.append("create_client") or MagicMock()):
        db_module.get_client()
    assert order == ["install", "create_client"]


def test_concurrent_callers_get_exactly_one_client(db_module, monkeypatch):
    """FastAPI runs sync dependencies in a threadpool and the webhook processor
    has its own thread, so two threads really can both observe None. A second
    client would mean a second pool that nothing ever closes."""
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "key")
    built = []
    start = threading.Barrier(12)

    def slow_create(*_a, **_k):
        built.append(1)
        return MagicMock()

    results = []
    with patch.object(T, "install", return_value={}), \
         patch.object(db_module, "create_client", side_effect=slow_create):
        def worker():
            start.wait()
            results.append(db_module.get_client())
        threads = [threading.Thread(target=worker) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert len(built) == 1, f"create_client ran {len(built)} times"
    assert len(results) == 12
    assert all(r is results[0] for r in results)


def test_close_client_closes_the_sessions_and_drops_the_reference(db_module):
    """httpx.Client.close() is terminal -- a closed client raises for the life
    of the process. Keeping a closed client cached would turn every straggler
    after SIGTERM into a hard 500."""
    client = MagicMock()
    session = httpx.Client()
    client.postgrest.session = session
    client.auth._http_client = httpx.Client()
    db_module._client = client
    db_module.close_client()
    assert session.is_closed is True
    assert db_module._client is None


def test_close_client_on_a_never_constructed_client_is_a_no_op(db_module):
    db_module._client = None
    db_module.close_client()  # must not raise


def test_one_failing_close_does_not_skip_the_other_session(db_module):
    client = MagicMock()
    client.postgrest.session.aclose.side_effect = RuntimeError("already gone")
    auth_session = httpx.Client()
    client.auth._http_client = auth_session
    db_module._client = client
    db_module.close_client()
    assert auth_session.is_closed is True


# ---------------------------------------------------------------------------
# Long-lived connection behaviour
# ---------------------------------------------------------------------------

class _IdleReapingHandler(BaseHTTPRequestHandler):
    """Answers, then silently drops the keepalive connection -- exactly what an
    idle-connection reaper in front of PostgREST does."""

    protocol_version = "HTTP/1.1"

    def do_GET(self):
        body = b'[{"ok":true}]'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.server.served += 1
        if self.server.served == 1:
            # No `Connection: close` header: the client is given no warning,
            # it just finds the socket gone on the next request.
            self.close_connection = True

    def log_message(self, *_a):
        pass


@pytest.fixture
def idle_reaping_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _IdleReapingHandler)
    server.served = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def test_http11_recovers_when_the_server_drops_a_pooled_connection(idle_reaping_server):
    """The W7D failure in one sentence: the server retired a long-lived pooled
    connection and the client did not renew it.

    Under HTTP/1.1 httpcore checks a pooled connection before handing it out
    and opens a fresh one, so the same event is invisible. (This exercises the
    pool over cleartext; the HTTP/2 half of the comparison needs TLS+ALPN and
    is covered by the live production proof, which asserts the negotiated
    protocol is HTTP/1.1.)"""
    host, port = idle_reaping_server.server_address[:2]
    with httpx.Client(
        base_url=f"http://{host}:{port}",
        http2=False,
        limits=T.build_limits(),
        timeout=T.build_timeout(),
    ) as client:
        first = client.get("/rest/v1/appointments")
        assert first.status_code == 200
        assert first.http_version == "HTTP/1.1"

        # The server has now dropped the connection under us.
        for _ in range(4):
            later = client.get("/rest/v1/appointments")
            assert later.status_code == 200, "a reaped connection must not fail the request"
            assert later.json() == [{"ok": True}]

    assert idle_reaping_server.served == 5


def test_a_pooled_connection_is_reused_when_the_server_keeps_it(idle_reaping_server):
    """The other half: we must not have traded the fault for a new connection
    on every call."""
    host, port = idle_reaping_server.server_address[:2]
    with httpx.Client(
        base_url=f"http://{host}:{port}",
        http2=False,
        limits=T.build_limits(),
        timeout=T.build_timeout(),
    ) as client:
        client.get("/x")            # this one gets dropped by the handler
        for _ in range(5):
            client.get("/x")
        pool = client._transport._pool
        assert len(pool.connections) == 1, f"expected one pooled connection, got {pool.connections}"
