"""
Provider transport with PROVIDER-SPECIFIC request encoding.

  * Vapi   -> JSON bodies, Content-Type: application/json
  * Twilio -> form bodies, Content-Type: application/x-www-form-urlencoded
  * GET/DELETE send no body; query params are encoded onto the URL, never the body.
  * Errors are sanitized (status + redacted snippet) — no credentials, full numbers,
    or raw sensitive bodies are logged.

The test seam is the ENCODED request: `_TRANSPORT` (when set) receives a fully
`PreparedRequest` (method, url, headers, encoded body bytes) and returns a
`RawResponse`. Tests therefore inspect real bytes/URLs/headers, not a pre-encoding
Python dict. When `_TRANSPORT` is None, real urllib I/O happens (apply only).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from ..sanitize import redact_secrets

# Test/interception seam (encoded level). None in real runs.
_TRANSPORT = None


class ProviderError(Exception):
    pass


@dataclass
class PreparedRequest:
    method: str
    url: str
    headers: dict = field(default_factory=dict)
    body: bytes | None = None
    provider: str = ""

    def content_type(self) -> str | None:
        return self.headers.get("Content-Type")

    def has_auth(self) -> bool:
        return "Authorization" in self.headers


@dataclass
class RawResponse:
    status: int
    text: str


def env(name: str, default: str = "") -> str:
    import os
    return os.environ.get(name, default)


def _form_flatten(body: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for k, v in (body or {}).items():
        if v is None:
            continue
        if isinstance(v, bool):
            out.append((k, "true" if v else "false"))
        else:
            out.append((k, str(v)))
    return out


class BaseProvider:
    ENCODING = "json"   # "json" (Vapi) or "form" (Twilio)
    NAME = "base"

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _auth_header(self) -> dict:  # pragma: no cover - overridden
        raise NotImplementedError

    # -- pure, unit-testable encoding --
    def prepare(self, method: str, path: str, body: dict | None = None,
                query: dict | None = None) -> PreparedRequest:
        method = method.upper()
        url = f"{self.base_url}{path}"
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        headers = dict(self._auth_header())
        data: bytes | None = None
        if method not in ("GET", "DELETE") and body is not None:
            if self.ENCODING == "form":
                data = urllib.parse.urlencode(_form_flatten(body)).encode("utf-8")
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                data = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
        return PreparedRequest(method, url, headers, data, self.NAME)

    def parse(self, text: str) -> dict:
        return json.loads(text) if text else {}

    # -- transport --
    def _send(self, prepared: PreparedRequest) -> RawResponse:
        if _TRANSPORT is not None:
            return _TRANSPORT(prepared)
        req = urllib.request.Request(prepared.url, data=prepared.body,
                                     headers=prepared.headers, method=prepared.method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - trusted hosts
                return RawResponse(resp.status, resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:  # pragma: no cover - network
            body = ""
            try:
                body = e.read().decode("utf-8", "ignore")
            except Exception:
                pass
            raise ProviderError(f"{self.NAME} {prepared.method} -> {e.code}: "
                                f"{redact_secrets(body)[:200]}") from None
        except urllib.error.URLError as e:  # pragma: no cover - network
            raise ProviderError(f"{self.NAME} {prepared.method} network error") from None

    def _http(self, method: str, path: str, body: dict | None = None,
              query: dict | None = None) -> dict:
        prepared = self.prepare(method, path, body, query)
        raw = self._send(prepared)
        if raw.status >= 400:
            raise ProviderError(f"{self.NAME} {method} {path} -> {raw.status}: "
                                f"{redact_secrets(raw.text)[:200]}")
        return self.parse(raw.text)
