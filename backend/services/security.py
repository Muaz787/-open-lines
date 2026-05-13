"""
Security guards for the knowledge base pipeline.

Three layers of protection:
  1. Tenant ownership — caller must own the tenant (JWT check)
  2. Prompt injection — block content that tries to hijack the AI's instructions
  3. SSRF protection — block URLs that resolve to private/internal networks
"""

import re
import ipaddress
import logging
from urllib.parse import urlparse

from fastapi import HTTPException

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
        pass  # hostname is a domain name, not a raw IP — that's fine
