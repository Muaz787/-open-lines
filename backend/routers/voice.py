"""
Custom-TTS bridge: Vapi <-> Fish Audio.

Vapi's `custom-voice` provider POSTs a voice-request to this endpoint for each
utterance; we proxy to Fish Audio's streaming TTS and stream the raw PCM back.
Both sides speak 16-bit mono little-endian PCM, so no transcoding is needed —
we just pass the requested sampleRate through to Fish.

Safety:
  - Auth via the existing VAPI_SERVER_SECRET (Vapi sends it as X-Vapi-Secret).
  - If Fish is unconfigured or fails, we return a non-200 so Vapi falls back to
    the ElevenLabs voice declared in the assistant's fallbackPlan — no dead air.
  - OFF by default: only tenants in FISH_TTS_CANARY_TENANT_IDS are routed here
    (that gating lives in services/vapi.build_voice_block, not this endpoint).

Env: FISH_API_KEY, FISH_VOICE_REFERENCE_ID, FISH_TTS_MODEL (default speech-1.6).
"""
import os
import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Header, Request, HTTPException
from fastapi.responses import StreamingResponse

from services.security import verify_vapi_server_secret

router = APIRouter(prefix="/voice", tags=["voice"])
logger = logging.getLogger(__name__)

FISH_TTS_URL = "https://api.fish.audio/v1/tts"


@router.post("/fish-tts")
async def fish_tts(request: Request, x_vapi_secret: Annotated[str | None, Header()] = None):
    """Stream Fish Audio PCM for one Vapi utterance. Any failure -> non-200 so
    Vapi uses the assistant's ElevenLabs fallbackPlan."""
    verify_vapi_server_secret(x_vapi_secret)  # 403 if secret missing/mismatched

    api_key = os.getenv("FISH_API_KEY", "")
    reference_id = os.getenv("FISH_VOICE_REFERENCE_ID", "")
    model = os.getenv("FISH_TTS_MODEL", "").strip()  # empty -> let Fish use its default
    if not api_key or not reference_id:
        logger.error("fish-tts: FISH_API_KEY or FISH_VOICE_REFERENCE_ID not set")
        raise HTTPException(status_code=503, detail="Fish TTS not configured")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    msg = (payload or {}).get("message") or {}
    text = (msg.get("text") or "").strip()
    sample_rate = int(msg.get("sampleRate") or 24000)
    if not text:
        raise HTTPException(status_code=400, detail="No text to synthesize")

    fish_payload = {
        "text": text,
        "reference_id": reference_id,
        "format": "pcm",          # raw 16-bit mono LE — exactly what Vapi expects
        "sample_rate": sample_rate,
        "latency": "balanced",    # ~300ms time-to-first-audio
    }
    # Fish accepts application/json (httpx sets it via json=) — no msgpack dep needed.
    headers = {"Authorization": f"Bearer {api_key}"}
    if model:
        headers["model"] = model  # only send when explicitly configured

    # Open the stream and check status BEFORE returning 200, so a Fish failure
    # surfaces as a non-200 to Vapi (which then uses the ElevenLabs fallback).
    client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
    try:
        req = client.build_request("POST", FISH_TTS_URL, headers=headers, json=fish_payload)
        resp = await client.send(req, stream=True)
    except Exception as e:
        await client.aclose()
        logger.error("fish-tts: connect error: %s", e)
        raise HTTPException(status_code=502, detail="Fish TTS unreachable")

    if resp.status_code != 200:
        detail = (await resp.aread())[:300]
        await resp.aclose()
        await client.aclose()
        logger.error("fish-tts: Fish API %s: %s", resp.status_code, detail)
        raise HTTPException(status_code=502, detail="Fish TTS error")

    async def stream():
        try:
            async for chunk in resp.aiter_bytes():
                if chunk:
                    yield chunk
        except Exception as e:
            logger.error("fish-tts: mid-stream error: %s", e)
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(stream(), media_type="application/octet-stream")
