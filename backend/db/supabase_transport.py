"""Explicit HTTP transport policy for the Supabase client.  (W7T)

WHY THIS MODULE EXISTS
----------------------
W7D failed in production with, on every single Square webhook delivery:

    httpx.RemoteProtocolError: <ConnectionTerminated error_code:0, last_stream_id:3>

error_code 0 is NO_ERROR: that is a *graceful* HTTP/2 GOAWAY, the normal way a
server or an intermediary retires a long-lived connection. The bug is what
happens next. `postgrest` builds its httpx session with `http2=True` hardcoded,
and httpx/httpcore surface a GOAWAY on a pooled HTTP/2 connection as a request
failure instead of renewing the connection (httpx discussion #2112, still open).
So the first PostgREST call after the proxy retires our connection raises, and
because our Railway process holds one module-global Supabase client for the
lifetime of the container, it raises for *every* caller until the pool happens
to rebuild. Locally the same code path never sees it: a short-lived script never
keeps a connection alive long enough to be retired.

THE POLICY
----------
1. HTTP/1.1, not HTTP/2. HTTP/1.1 connection reuse is handled correctly by
   httpcore: a closed idle connection is dropped from the pool rather than
   handed out. We gain nothing from HTTP/2 here -- PostgREST traffic is a
   handful of small sequential requests, never the many-parallel-streams shape
   HTTP/2 exists for.
2. An explicit keepalive expiry SHORTER than any plausible server-side idle
   timeout, so *we* retire idle sockets first instead of discovering that the
   other end already did.
3. Explicit pool limits, so a burst cannot open unbounded sockets.
4. An explicit, component-wise timeout. postgrest's default is a flat 120s on
   every phase, which means a hung connect blocks a webhook handler for two
   minutes and Square retries on top of it.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
-----------------------------------------
No retries, and no automatic client recreation. Both are designed in the W7T PR
description but not implemented here: a retry that is added before the transport
is correct just multiplies a broken request, and recreation needs an ownership
model for the in-flight callers of the client being replaced. Transport first.

HOW THE POLICY IS APPLIED
-------------------------
Not by swapping `client.postgrest.session` after construction. That swap does
not hold:

  * `supabase.Client.postgrest` is a lazily-cached property, and
    `_listen_to_auth_events` sets `self._postgrest = None` on SIGNED_IN /
    TOKEN_REFRESHED / SIGNED_OUT -- the next access silently rebuilds an
    HTTP/2 session.
  * `SyncPostgrestClient.schema()` constructs a fresh client too.

`ClientOptions` exposes no transport hook and `supabase 2.15.0` pins
`postgrest (>0.19,<1.1)`, so postgrest 1.1's injectable-client API is not
reachable without moving supabase itself. The one place that is both a single
point and durable is the name each library calls to construct its session:
`postgrest._sync.client.SyncClient` and `gotrue._sync.gotrue_base_api.SyncClient`.
We rebind those to a factory that applies the policy and then constructs the
library's own class, so every future construction -- including the two rebuild
paths above -- is covered.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)

# The transport stack this policy was written against and tested on. A mismatch
# is not fatal -- the policy is applied regardless -- but it is logged, because
# `postgrest`, `httpcore` and `h2` were unpinned before W7T and a fresh Railway
# build could otherwise install a different stack than the one we proved.
TESTED_VERSIONS = {
    "supabase": "2.15.0",
    "postgrest": "1.0.2",
    "gotrue": "2.12.4",
    "httpx": "0.27.2",
    "httpcore": "1.0.9",
    "h2": "4.3.0",
}

# Defaults. Every one is overridable by env so a production incident can be
# tuned without a deploy, but the defaults are the tested configuration.
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 30.0
DEFAULT_WRITE_TIMEOUT = 30.0
DEFAULT_POOL_TIMEOUT = 5.0
DEFAULT_MAX_CONNECTIONS = 20
DEFAULT_MAX_KEEPALIVE = 10
# Shorter than any plausible upstream idle timeout (Supabase's edge and
# Railway's egress both sit well above this), so we close first.
DEFAULT_KEEPALIVE_EXPIRY = 30.0

_install_lock = threading.Lock()
_installed = False
_patched: dict[str, str] = {}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("supabase transport: %s=%r is not a number; using %s", name, raw, default)
        return default
    if value <= 0:
        logger.warning("supabase transport: %s=%r must be > 0; using %s", name, raw, default)
        return default
    return value


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("supabase transport: %s=%r is not an integer; using %s", name, raw, default)
        return default
    if value <= 0:
        logger.warning("supabase transport: %s=%r must be > 0; using %s", name, raw, default)
        return default
    return value


def http2_enabled() -> bool:
    """HTTP/2 is off unless someone deliberately turns it back on.

    The escape hatch exists so that if HTTP/1.1 ever turns out to be the wrong
    call in production it can be reversed by an env var rather than a rollback.
    """
    return (os.getenv("SUPABASE_HTTP2") or "").strip().lower() in {"1", "true", "yes", "on"}


def build_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        connect=_env_float("SUPABASE_HTTP_CONNECT_TIMEOUT", DEFAULT_CONNECT_TIMEOUT),
        read=_env_float("SUPABASE_HTTP_READ_TIMEOUT", DEFAULT_READ_TIMEOUT),
        write=_env_float("SUPABASE_HTTP_WRITE_TIMEOUT", DEFAULT_WRITE_TIMEOUT),
        pool=_env_float("SUPABASE_HTTP_POOL_TIMEOUT", DEFAULT_POOL_TIMEOUT),
    )


def build_limits() -> httpx.Limits:
    max_connections = _env_int("SUPABASE_HTTP_MAX_CONNECTIONS", DEFAULT_MAX_CONNECTIONS)
    max_keepalive = _env_int("SUPABASE_HTTP_MAX_KEEPALIVE", DEFAULT_MAX_KEEPALIVE)
    # A keepalive ceiling above the connection ceiling is meaningless; clamp it
    # rather than let a typo produce a pool that behaves unlike the tested one.
    if max_keepalive > max_connections:
        max_keepalive = max_connections
    return httpx.Limits(
        max_connections=max_connections,
        max_keepalive_connections=max_keepalive,
        keepalive_expiry=_env_float("SUPABASE_HTTP_KEEPALIVE_EXPIRY", DEFAULT_KEEPALIVE_EXPIRY),
    )


def _make_factory(original_cls: type, component: str) -> Callable[..., Any]:
    """Wrap a library's httpx.Client subclass in our transport policy.

    The library's own class is still what gets constructed -- both `postgrest`
    and `gotrue` subclass `httpx.Client` only to add an `aclose()` alias, and
    both call it on shutdown, so returning a bare `httpx.Client` here would
    break close paths.
    """

    def factory(*args: Any, **kwargs: Any) -> Any:
        kwargs["http2"] = http2_enabled()
        kwargs["limits"] = build_limits()
        kwargs["timeout"] = build_timeout()
        kwargs.setdefault("follow_redirects", True)
        return original_cls(*args, **kwargs)

    factory.__name__ = f"hardened_{component}_client"
    factory.__qualname__ = factory.__name__
    factory.__doc__ = (
        f"W7T transport policy applied to {original_cls.__module__}.{original_cls.__qualname__}."
    )
    # Kept so tests (and `describe()`) can prove what we wrapped without
    # reaching into the closure.
    factory.wrapped_cls = original_cls  # type: ignore[attr-defined]
    factory.component = component  # type: ignore[attr-defined]
    return factory


# The construction sites we rebind. Both are `from ..utils import SyncClient`
# style imports, so rebinding the attribute on the *consuming* module replaces
# exactly the one call site and leaves the library's own class untouched for
# everyone else.
_TARGETS = (
    ("postgrest", "postgrest._sync.client", "SyncClient"),
    ("gotrue", "gotrue._sync.gotrue_base_api", "SyncClient"),
)


def install() -> dict[str, str]:
    """Apply the transport policy. Idempotent, thread-safe, and fails open.

    MUST run before `supabase.create_client()`. `db.supabase.get_client()`
    calls it, which is the only construction site in this codebase.

    Fails open deliberately: a library refactor that moves one of these names
    must not take the API down. It downgrades us to the pre-W7T behaviour for
    that component and says so loudly, and the startup diagnostic then reports
    the component as unhardened.
    """
    global _installed
    with _install_lock:
        if _installed:
            return dict(_patched)
        import importlib

        for component, module_path, attr in _TARGETS:
            try:
                module = importlib.import_module(module_path)
                original = getattr(module, attr)
                if getattr(original, "component", None) == component:
                    _patched[component] = "already-patched"
                    continue
                setattr(module, attr, _make_factory(original, component))
                _patched[component] = f"{module_path}.{attr}"
            except Exception as exc:  # pragma: no cover - library-shape change
                logger.error(
                    "supabase transport: could not harden %s (%s.%s): %s -- "
                    "that component keeps the library default (HTTP/2)",
                    component, module_path, attr, exc,
                )
                _patched[component] = f"FAILED: {type(exc).__name__}"
        _installed = True
        _log_version_drift()
        logger.info(
            "supabase transport: http2=%s keepalive_expiry=%ss patched=%s",
            http2_enabled(), build_limits().keepalive_expiry, sorted(_patched),
        )
        return dict(_patched)


def installed_versions() -> dict[str, str]:
    import importlib.metadata as metadata

    out: dict[str, str] = {}
    for package in TESTED_VERSIONS:
        try:
            out[package] = metadata.version(package)
        except Exception:
            out[package] = "not-installed"
    return out


def _log_version_drift() -> None:
    found = installed_versions()
    drift = {p: (found[p], v) for p, v in TESTED_VERSIONS.items() if found[p] != v}
    if drift:
        logger.warning(
            "supabase transport: dependency drift from the tested stack: %s",
            "; ".join(f"{p}: installed {got}, tested {want}" for p, (got, want) in drift.items()),
        )


def session_http2_enabled(session: Any) -> bool | None:
    """Read the *actual* protocol the pool behind an httpx client will speak.

    Deliberately reads httpcore's private `_http2` rather than trusting the
    constructor argument: the whole point of the startup assertion is to catch
    the case where the policy did not take effect, and a value we wrote
    ourselves cannot catch that. Returns None if the shape is unrecognised, so
    an httpcore refactor reads as "unknown", never as a false pass.
    """
    pool = getattr(getattr(session, "_transport", None), "_pool", None)
    value = getattr(pool, "_http2", None)
    return bool(value) if isinstance(value, bool) else None


def describe(client: Any) -> dict[str, Any]:
    """Transport diagnostic. Contains NO url, key, header or token.

    Only protocol, pool and timeout shape -- the things that decide whether the
    W7D failure can recur. Safe to log on every boot.
    """
    limits = build_limits()
    timeout = build_timeout()
    info: dict[str, Any] = {
        "policy_http2": http2_enabled(),
        "patched": dict(_patched),
        "limits": {
            "max_connections": limits.max_connections,
            "max_keepalive_connections": limits.max_keepalive_connections,
            "keepalive_expiry": limits.keepalive_expiry,
        },
        "timeout": {
            "connect": timeout.connect,
            "read": timeout.read,
            "write": timeout.write,
            "pool": timeout.pool,
        },
        "versions": installed_versions(),
        "sessions": {},
    }
    for name, session in _live_sessions(client).items():
        info["sessions"][name] = {
            "http2": session_http2_enabled(session),
            "timeout_connect": getattr(getattr(session, "timeout", None), "connect", None),
            "timeout_read": getattr(getattr(session, "timeout", None), "read", None),
        }
    return info


def _live_sessions(client: Any) -> dict[str, Any]:
    """The httpx clients actually in use, by name.

    Touching `client.postgrest` constructs it, which is intended: we want the
    session that will serve the first real request to exist and be asserted at
    boot, not at 3am on the first webhook.
    """
    sessions: dict[str, Any] = {}
    try:
        sessions["postgrest"] = client.postgrest.session
    except Exception as exc:  # pragma: no cover
        logger.warning("supabase transport: no postgrest session to inspect: %s", exc)
    try:
        sessions["auth"] = client.auth._http_client
    except Exception as exc:  # pragma: no cover
        logger.warning("supabase transport: no auth session to inspect: %s", exc)
    return sessions


def assert_hardened(client: Any) -> dict[str, Any]:
    """Verify the policy actually took, and report it. Never raises.

    Returns the diagnostic. A failure here means the process is running the
    configuration that broke W7D, which is worth a loud log line -- but not
    worth refusing to boot: a backend that is down is strictly worse than a
    backend on the transport it has been running on all along.
    """
    info = describe(client)
    expected = http2_enabled()
    for name, session in info["sessions"].items():
        actual = session["http2"]
        if actual is None:
            logger.warning(
                "supabase transport: could not determine the %s protocol "
                "(httpcore internals changed?) -- treat as UNVERIFIED", name,
            )
        elif actual != expected:
            logger.error(
                "supabase transport: %s session has http2=%s but policy wants %s "
                "-- the W7D GOAWAY failure mode is NOT mitigated for this component",
                name, actual, expected,
            )
        else:
            logger.info("supabase transport: %s session verified http2=%s", name, actual)
    return info


def close_sessions(client: Any) -> None:
    """Close every httpx client the Supabase client holds.

    Called on shutdown so Railway's SIGTERM does not leave sockets in the
    server's accept queue during a rolling deploy. Best-effort per session: one
    failing close must not skip the others.
    """
    for name, session in _live_sessions(client).items():
        try:
            close = getattr(session, "aclose", None) or getattr(session, "close", None)
            if close is not None:
                close()
        except Exception as exc:  # pragma: no cover
            logger.warning("supabase transport: closing the %s session failed: %s", name, exc)
