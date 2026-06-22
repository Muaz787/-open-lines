"""
Security helpers for Open Lines:
  1. Tenant ownership — caller must own the tenant (JWT check)
  2. Prompt injection — block content that tries to hijack the AI instructions
  3. SSRF protection — block URLs that resolve to private/internal networks
  4. AES-256-GCM encryption — for sub-org API keys stored in Supabase
"""

import os
import re
import base64
import ipaddress
import logging
from typing import Annotated
from urllib.parse import urlparse

from fastapi import HTTPException, Header, Request

# ---------------------------------------------------------------------------
# 4. AES-256-GCM symmetric encryption
# ---------------------------------------------------------------------------
# Set ENCRYPTION_KEY_HEX in your environment to a 64-char hex string (32 bytes).
# Generate one with: python -c "import os,binascii; print(binascii.hexlify(os.urandom(32)).decode())"
#
# Keys stored with this scheme: nonce (12 bytes) | ciphertext+tag (variable)
# Base64url-encoded, safe to store in any text column.

def _get_enc_key() -> bytes:
    hex_key = os.getenv("ENCRYPTION_KEY_HEX", "")
    if len(hex_key) != 64:
        raise RuntimeError(
            "ENCRYPTION_KEY_HEX must be set to a 64-character hex string (32 bytes). "
            "Generate one with: python -c \"import os,binascii; print(binascii.hexlify(os.urandom(32)).decode())\""
        )
    return bytes.fromhex(hex_key)


def encrypt(plaintext: str) -> str:
    """AES-256-GCM encrypt. Returns a base64url token safe to store in a text column."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _get_enc_key()
    nonce = os.urandom(12)  # 96-bit nonce — unique per encryption
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ct).decode("ascii")


def decrypt(token: str) -> str:
    """AES-256-GCM decrypt. Raises ValueError on tampered or wrong-key data."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
        nonce, ct = raw[:12], raw[12:]
        return AESGCM(_get_enc_key()).decrypt(nonce, ct, None).decode("utf-8")
    except Exception as exc:
        raise ValueError(f"Decryption failed: {exc}") from exc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Tenant ownership
# ---------------------------------------------------------------------------

async def verify_tenant_owner(tenant_id: str, authorization: str | None) -> None:
    """Raise HTTP 401/403 unless the Bearer token belongs to this tenant."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        from db.supabase import get_client
        user_response = get_client().auth.get_user(token)
        user = user_response.user
        if not user:
            raise ValueError("no user in token response")
        user_tenant_id = (user.user_metadata or {}).get("tenant_id")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Token verification failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if user_tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Access denied")


async def require_tenant_owner(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """FastAPI dependency form of verify_tenant_owner for routes that carry the
    tenant id as a `{tenant_id}` path parameter. Use as a router-level dependency
    when EVERY route in the router is tenant-owner-scoped.

    Never trusts the path tenant_id alone — it is only honoured after the bearer
    token is verified to belong to that tenant.
    """
    tenant_id = request.path_params.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    await verify_tenant_owner(tenant_id, authorization)


# ---------------------------------------------------------------------------
# 1b. Vapi shared-secret verification (server webhooks + mid-call tool calls)
# ---------------------------------------------------------------------------

_vapi_secret_warned = False


def verify_vapi_server_secret(x_vapi_secret: str | None) -> None:
    """Verify the shared secret Vapi sends (as X-Vapi-Secret) on server webhooks
    and mid-call tool requests. Backward-compatible: when VAPI_SERVER_SECRET is
    unset we log once and allow, so live calls keep working until it's configured
    in both Vapi and the environment."""
    global _vapi_secret_warned
    secret = os.getenv("VAPI_SERVER_SECRET", "")
    if not secret:
        if not _vapi_secret_warned:
            logger.warning(
                "VAPI_SERVER_SECRET not set — Vapi webhook/tool authenticity is NOT "
                "enforced. Set it in Vapi (server secret) and as an env var to close this."
            )
            _vapi_secret_warned = True
        return
    if x_vapi_secret != secret:
        logger.warning("Vapi request rejected: missing/invalid X-Vapi-Secret")
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


# ---------------------------------------------------------------------------
# 2. Prompt injection detection
# ---------------------------------------------------------------------------

# Patterns that signal an attempt to override AI instructions
_INJECTION_PATTERNS: list[re.Pattern] = [
    # Classic override phrasing
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above|earlier|your)\s+(instructions?|rules?|constraints?|guidelines?)", re.I),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above|earlier|your)\s+(instructions?|rules?|constraints?)", re.I),
    re.compile(r"forget\s+(everything|all)\s+(you\s+know|above|i\s+said)", re.I),
    re.compile(r"do\s+not\s+follow\s+(your|the)\s+(previous|prior|original)\s+instructions?", re.I),

    # Role / persona hijacking
    re.compile(r"you\s+are\s+now\s+(?!an?\s+(AI|assistant|phone|voice|receptionist))", re.I),
    re.compile(r"act\s+as\s+(if\s+)?(you\s+(are|were)|a\s+)", re.I),
    re.compile(r"pretend\s+(you\s+are|to\s+be)", re.I),
    re.compile(r"your\s+(new\s+)?(role|persona|identity|instructions?|name)\s+(is|are)\s*:", re.I),
    re.compile(r"from\s+now\s+on\s+(you\s+are|act)", re.I),

    # DAN / jailbreak keywords
    re.compile(r"\bDAN\b.*jailbreak|\bjailbreak\b.*\bDAN\b", re.I),
    re.compile(r"do\s+anything\s+now", re.I),
    re.compile(r"jailbroken?\b", re.I),
    re.compile(r"enable\s+(developer|dev)\s+mode", re.I),

    # System prompt injection markers
    re.compile(r"<\|?(system|im_start|im_end|endoftext)\|?>", re.I),
    re.compile(r"\[SYSTEM\]|\[INST\]|\[\/INST\]", re.I),
    re.compile(r"###\s*(instruction|system|human|assistant)\b", re.I),

    # New system prompt / instruction injection
    re.compile(r"new\s+system\s+prompt", re.I),
    re.compile(r"override\s+(the\s+)?(system\s+)?prompt", re.I),
    re.compile(r"your\s+(actual|real|true|original)\s+(instructions?|purpose)", re.I),

    # Exfiltration attempts
    re.compile(r"reveal\s+(your|the)\s+(system\s+)?(prompt|instructions?|configuration)", re.I),
    re.compile(r"(print|output|repeat|show|display|leak)\s+(your\s+)?(system\s+prompt|instructions?)", re.I),
    re.compile(r"what\s+(is|are)\s+your\s+(exact\s+)?(instructions?|system\s+prompt)", re.I),
]

MAX_TEXT_CHARS = 100_000  # 100 KB of plain text per submission


def scan_for_injection(text: str, source: str = "input") -> None:
    """Raise HTTP 400 if the text contains prompt injection patterns."""
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Text exceeds {MAX_TEXT_CHARS:,} character limit ({len(text):,} chars submitted)",
        )

    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            logger.warning("Prompt injection attempt detected in %s: pattern=%s", source, pattern.pattern[:60])
            raise HTTPException(
                status_code=400,
                detail="Content rejected: contains patterns that could interfere with AI behaviour. "
                       "Please review and resubmit without instruction-override language.",
            )


# Tenant tries to configure the assistant for clearly disallowed behaviour.
# Kept deliberately conservative to avoid blocking legitimate business instructions.
_UNSAFE_USE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(pose|pretend|claim|act|say\s+you('?re|\s+are)|impersonat\w*)\b.{0,40}\b(police|officer|government|gov't|irs|cra|tax\s+(agency|authority)|bank|lawyer|attorney|doctor|physician|nurse|paramedic|federal\s+agent)\b", re.I),
     "configuring the assistant to impersonate police, government, a bank, or a regulated professional"),
    (re.compile(r"\b(tell|instruct|encourage|help|get)\b.{0,30}\b(caller|customer|client|them|people)\b.{0,45}\b(break\s+the\s+law|do(ing)?\s+something\s+illegal|commit\s+\w+|launder|evade\s+tax|lie\s+to)\b", re.I),
     "instructing the assistant to encourage illegal activity"),
    (re.compile(r"\b(ask\s+for|collect|request|take\s+down|read\s+back)\b.{0,40}\b(credit[-\s]?card|card\s+number|cvv|cvc|full\s+card|social\s+security|ssn|sin\s+number)\b", re.I),
     "asking the assistant to collect full card numbers or government IDs over the phone (use the secure deposit link instead)"),
    (re.compile(r"\b(don'?t|do\s+not|never)\b.{0,30}\b(tell|disclose|reveal|admit|say)\b.{0,25}\b(you('?re|\s+are)|it('?s|\s+is)|being)\b.{0,12}\b(an?\s+)?(ai|bot|robot|automated|machine|computer)\b", re.I),
     "instructing the assistant to hide that it is an AI"),
    (re.compile(r"\b(send|forward|email|text)\b.{0,30}\b(customer|caller|client|their|all)\b.{0,22}\b(data|info(rmation)?|details|records|numbers?)\b.{0,18}\bto\b", re.I),
     "instructing the assistant to send customer data to an external destination"),
]


def validate_business_instructions(text: str, field: str = "instructions") -> None:
    """Validate tenant-authored free-text (extra instructions, booking rules, FAQs).
    Rejects prompt-injection and clearly unsafe configuration with an explanatory error
    so the owner knows exactly which part is not allowed and how to fix it."""
    if not text or not text.strip():
        return
    scan_for_injection(text, source=field)  # raises 400 on injection / over-length
    for pattern, reason in _UNSAFE_USE_PATTERNS:
        if pattern.search(text):
            logger.warning("Unsafe business instruction blocked in %s: %s", field, reason)
            raise HTTPException(
                status_code=400,
                detail=(
                    f"These {field} can't be saved because they appear to be {reason}. "
                    "Open Lines assistants must stay lawful, identify as AI when asked, and never "
                    "collect sensitive data over the phone. Please reword to cover only how the "
                    "assistant should greet, qualify, schedule, and answer questions about your business."
                ),
            )


# ---------------------------------------------------------------------------
# 3. SSRF protection
# ---------------------------------------------------------------------------

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # AWS/GCP metadata
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 ULA
]

_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}


def validate_public_url(url: str) -> None:
    """Raise HTTP 400 if the URL targets a private/internal address (SSRF prevention)."""
    try:
        parsed = urlparse(url)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL")

    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="URL must use http or https")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise HTTPException(status_code=400, detail="URL has no hostname")

    if hostname in _BLOCKED_HOSTNAMES:
        raise HTTPException(status_code=400, detail="URL targets a disallowed hostname")

    # Try to parse as an IP address directly
    try:
        addr = ipaddress.ip_address(hostname)
        for network in _PRIVATE_NETWORKS:
            if addr in network:
                raise HTTPException(status_code=400, detail="URL targets a private or internal network address")
    except ValueError:
        pass  # hostname is a domain name, not a raw IP — resolve it below

    # Resolve the hostname and verify EVERY resolved IP is public. This blocks
    # DNS-rebinding and domains that deliberately point at internal/cloud-metadata
    # addresses (e.g. a hostname that resolves to 169.254.169.254 or 10.x).
    import socket
    try:
        infos = socket.getaddrinfo(hostname, None)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not resolve URL host")

    for info in infos:
        ip_str = info[4][0]
        try:
            resolved = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (not resolved.is_global) or any(resolved in net for net in _PRIVATE_NETWORKS):
            raise HTTPException(status_code=400, detail="URL resolves to a private or internal network address")
