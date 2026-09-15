"""
Hardened capture + dynamic-destination webhook (stdlib only).

Security controls:
  * exact allowed path = /hook/<run_id>  (health = /healthz)
  * explicit method rejection (405), wrong path (404)
  * Content-Type must be application/json (415)
  * max body size (413)
  * constant-time shared-secret auth via X-Vapi-Secret (403); secret never logged
  * unique run-id validation (encoded in the path)
  * mode / bound-assistant consistency before returning a destination
  * dynamic response is a BARE authorized destination — it cannot alter the mode
    (the complete mode-specific transferPlan lives on the assistant tool)
  * atomic, lock-guarded, sanitized-before-write evidence (0600 in a 0700 dir)
  * health endpoint carries no secrets; graceful shutdown on SIGINT/SIGTERM

The request logic lives in `handle_request()` (socket-free) so it is unit-tested
directly, including concurrency.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import signal
import stat
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import constants as C
from . import safety
from .logging_setup import get_logger
from .sanitize import sanitize_event

log = get_logger("phase0.capture")


# --- config -----------------------------------------------------------------

@dataclass
class CaptureConfig:
    secret: str
    run_id: str
    mode: str
    dest: str
    allowlist: list[str]
    base: str
    manifest: dict

    @property
    def webhook_path(self) -> str:
        return f"{C.WEBHOOK_PATH_PREFIX}/{self.run_id}"


def load_config(env: dict | None = None) -> CaptureConfig:
    env = env if env is not None else os.environ
    base = env.get("PHASE0_BASE", ".")
    manifest = _safe_manifest(base)
    return CaptureConfig(
        secret=env.get("VAPI_SERVER_SECRET", ""),
        run_id=env.get("PHASE0_RUN_ID", ""),
        mode=env.get("PHASE0_MODE", ""),
        dest=env.get("PHASE0_DEST", ""),
        allowlist=[a for a in env.get("PHASE0_DEST_ALLOWLIST", "").split(",") if a.strip()],
        base=base,
        manifest=manifest,
    )


def _safe_manifest(base: str) -> dict:
    """Read the CURRENT operational manifest. Missing/malformed/unreadable → {}.
    Reads are safe against provisioning's atomic replace (os.replace)."""
    from . import manifest as M
    try:
        data = M.read_operational(base)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


# --- evidence writer (locked, atomic append) --------------------------------

class EvidenceWriter:
    def __init__(self, base: str):
        d = os.path.join(base, C.EVIDENCE_DIR_NAME)
        os.makedirs(d, exist_ok=True)
        os.chmod(d, stat.S_IRWXU)
        self.path = os.path.join(d, f"events-{datetime.now(timezone.utc):%Y%m%d}.jsonl")
        self._lock = threading.Lock()

    def write_event(self, event_type: str, body: dict) -> None:
        clean = sanitize_event(event_type, body)   # sanitize BEFORE persistence
        clean["_captured_at"] = datetime.now(timezone.utc).isoformat()
        line = json.dumps(clean) + "\n"
        with self._lock:                            # atomic w.r.t. other writers
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
            try:
                os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass


# --- consistency + destination ----------------------------------------------

def mode_consistent(manifest: dict, mode: str) -> bool:
    """PHASE0_MODE must match the assistant currently bound to the phone number."""
    if manifest.get("selected_mode") != mode:
        return False
    key = "assistant_id_m1" if mode == C.MODE_M1 else "assistant_id_m2"
    bound = manifest.get("bound_assistant_id")
    return bool(bound) and bound == manifest.get(key)


def run_id_hash(run_id: str) -> str:
    """Non-secret, stable identifier the health endpoint exposes so live-preflight
    can confirm the capture process is bound to the intended PHASE0_RUN_ID."""
    return hashlib.sha256((run_id or "").encode()).hexdigest()[:12]


def health_body(cfg: "CaptureConfig") -> dict:
    """Live health snapshot (no secrets). Re-reads the manifest from disk so
    `manifest_loaded` reflects current state, not process-start state. Before
    provisioning this reports manifest_loaded=false, which is EXPECTED and does NOT
    mean the line is ready for calls (see the lifecycle `state` command)."""
    fresh = _safe_manifest(cfg.base)
    loaded = bool(fresh.get("bound_assistant_id"))
    return {
        "status": "ok",
        "run_id_present": bool(cfg.run_id),
        "run_id_hash": run_id_hash(cfg.run_id),
        "mode": cfg.mode,
        "manifest_loaded": loaded,
        "mode_consistent": (loaded and mode_consistent(fresh, cfg.mode)),
    }


def authorized_destination(cfg: CaptureConfig) -> dict:
    """A BARE authorized destination — no mode/transferPlan, so dynamic selection
    can never change the mode. Validated against the allow-list + number class.

    The operational manifest is reloaded LIVE here (not the process-start copy) so a
    missing, malformed, or unreadable manifest fails the transfer closed, and mode
    consistency reflects the current bound assistant."""
    safety.assert_destination_allowed(cfg.dest, cfg.allowlist)
    fresh = _safe_manifest(cfg.base)
    if not fresh.get("bound_assistant_id"):
        raise safety.SafetyError("operational manifest not loaded/incomplete — refusing transfer")
    if not mode_consistent(fresh, cfg.mode):
        raise safety.SafetyError("PHASE0_MODE does not match the bound assistant in the live manifest")
    return {"destination": {"type": "number", "number": cfg.dest, "numberE164CheckEnabled": True}}


# --- request handling (socket-free) -----------------------------------------

def handle_request(method: str, path: str, headers: dict, body: bytes,
                   cfg: CaptureConfig, writer: EvidenceWriter) -> tuple[int, dict]:
    h = {k.lower(): v for k, v in (headers or {}).items()}

    if method == "GET":
        if path == C.HEALTH_PATH:
            return 200, health_body(cfg)   # no secrets; live manifest_loaded/mode
        return 404, {"error": "not_found"}
    if method != "POST":
        return 405, {"error": "method_not_allowed"}

    # POST only past here.
    if path != cfg.webhook_path:
        return 404, {"error": "not_found"}          # wrong path / wrong run id
    if not (h.get("content-type", "").startswith(C.REQUIRED_CONTENT_TYPE)):
        return 415, {"error": "unsupported_media_type"}
    if body is not None and len(body) > C.MAX_BODY_BYTES:
        return 413, {"error": "payload_too_large"}
    if not cfg.secret:
        return 500, {"error": "server_misconfigured"}   # empty secret => refuse
    got = h.get(C.VAPI_SECRET_HEADER.lower(), "")
    if not hmac.compare_digest(got, cfg.secret):        # constant-time
        return 403, {"error": "forbidden"}

    try:
        payload = json.loads(body or b"{}")
    except Exception:
        return 400, {"error": "bad_json"}
    msg = payload.get("message", payload)
    event_type = msg.get("type", "")
    writer.write_event(event_type, msg)                 # sanitized inside

    if event_type == "transfer-destination-request":
        try:
            return 200, authorized_destination(cfg)
        except safety.SafetyError as e:
            log.info("destination refused: %s", e)
            return 200, {"error": "no_authorized_destination"}
    return 200, {"status": "ok"}


# --- HTTP server wrapper -----------------------------------------------------

def _make_handler(cfg: CaptureConfig, writer: EvidenceWriter):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):   # suppress default request logging (no bodies)
            return

        def _reply(self, status: int, obj: dict):
            raw = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _dispatch(self, method: str):
            length = int(self.headers.get("Content-Length", "0") or "0")
            length = min(length, C.MAX_BODY_BYTES + 1)      # never read unbounded
            body = self.rfile.read(length) if length else b""
            status, obj = handle_request(method, self.path, dict(self.headers), body, cfg, writer)
            self._reply(status, obj)

        def do_GET(self):    # noqa: N802
            self._dispatch("GET")

        def do_POST(self):   # noqa: N802
            self._dispatch("POST")

        def do_PUT(self):    # noqa: N802
            self._reply(405, {"error": "method_not_allowed"})

        do_DELETE = do_PUT
        do_PATCH = do_PUT

    return Handler


def main():  # pragma: no cover - runtime entrypoint
    cfg = load_config()
    writer = EvidenceWriter(cfg.base)
    port = int(os.environ.get("PHASE0_PORT", "8099"))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(cfg, writer))

    def _shutdown(*_a):
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    log.info("capture listening on 127.0.0.1:%s path=%s", port, cfg.webhook_path)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        log.info("capture shut down cleanly")


if __name__ == "__main__":  # pragma: no cover
    main()
