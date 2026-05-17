import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Header, UploadFile, File
from typing import Annotated
from pydantic import BaseModel

from db import supabase as db
from services import knowledge
from services.provisioning import rebuild_and_push_system_prompt
from services.security import verify_tenant_owner, scan_for_injection, validate_public_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


async def _reprompt_after_change(tenant: dict) -> None:
    """Non-fatal reprompt — logs a warning on failure so the KB response is never blocked."""
    try:
        await rebuild_and_push_system_prompt(tenant)
        logger.info("System prompt rebuilt after KB change for tenant %s", tenant["id"])
    except Exception as e:
        logger.warning("Reprompt after KB change failed for tenant %s (non-fatal): %s", tenant["id"], e)

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB per file
MAX_FILES = 10


class TextRequest(BaseModel):
    text: str


class WebsiteRequest(BaseModel):
    website_url: str


@router.patch("/website/{tenant_id}")
async def update_website_url(
    tenant_id: str,
    body: WebsiteRequest,
    authorization: Annotated[str | None, Header()] = None,
):
    await verify_tenant_owner(tenant_id, authorization)
    validate_public_url(body.website_url.strip())

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("Tenant lookup failed for %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Tenant lookup failed")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    url = body.website_url.strip()
    await db.update_tenant(tenant_id, {"website_url": url})
    logger.info("Updated website_url for tenant %s → %s", tenant_id, url)
    return {"status": "ok", "website_url": url}


@router.post("/upload/{tenant_id}")
async def upload_documents(
    tenant_id: str,
    files: list[UploadFile] = File(...),
    authorization: Annotated[str | None, Header()] = None,
):
    await verify_tenant_owner(tenant_id, authorization)

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("Tenant lookup failed for %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Tenant lookup failed")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    namespace: str = tenant["pinecone_namespace"]

    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_FILES} files per upload")

    results = []
    for file in files:
        fname = file.filename or "unknown"
        content = await file.read()

        if len(content) > MAX_FILE_BYTES:
            results.append({"file": fname, "status": "skipped", "reason": "exceeds 10 MB limit"})
            continue

        try:
            text = knowledge.extract_text(fname, content)
        except ValueError as e:
            results.append({"file": fname, "status": "error", "reason": str(e)})
            continue

        if not text.strip():
            results.append({"file": fname, "status": "skipped", "reason": "no readable text found"})
            continue

        try:
            scan_for_injection(text, source=f"file:{fname}")
        except HTTPException as e:
            results.append({"file": fname, "status": "error", "reason": e.detail})
            continue

        try:
            vectors = await knowledge.embed_and_store(namespace, text, tenant_id)
            results.append({"file": fname, "status": "ok", "vectors_stored": vectors})
            logger.info("Uploaded %s for tenant %s → %d vectors", fname, tenant_id, vectors)
        except Exception as e:
            logger.error("Failed to embed %s for tenant %s: %s", fname, tenant_id, e)
            results.append({"file": fname, "status": "error", "reason": "embedding failed"})

    if any(r["status"] == "ok" for r in results):
        await _reprompt_after_change(tenant)
        # Track successfully uploaded file names
        now = datetime.now(timezone.utc).isoformat()
        existing: list = tenant.get("kb_files") or []
        new_entries = [
            {"name": r["file"], "uploaded_at": now}
            for r in results if r["status"] == "ok"
        ]
        # Avoid duplicates by name; keep newest
        names_added = {e["name"] for e in new_entries}
        kept = [f for f in existing if f.get("name") not in names_added]
        await db.update_tenant(tenant_id, {"kb_files": kept + new_entries})

    return {"tenant_id": tenant_id, "results": results}


@router.post("/text/{tenant_id}")
async def add_text(
    tenant_id: str,
    body: TextRequest,
    authorization: Annotated[str | None, Header()] = None,
):
    await verify_tenant_owner(tenant_id, authorization)

    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text cannot be empty")

    scan_for_injection(body.text, source="manual text")

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("Tenant lookup failed for %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Tenant lookup failed")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    namespace: str = tenant["pinecone_namespace"]
    try:
        vectors = await knowledge.embed_and_store(namespace, body.text, tenant_id)
        logger.info("Added manual text for tenant %s → %d vectors", tenant_id, vectors)
    except Exception as e:
        err = str(e)
        logger.error("Failed to embed text for tenant %s: %s", tenant_id, err)
        if "dimension" in err.lower():
            raise HTTPException(status_code=500, detail="Pinecone index dimension mismatch — check PINECONE_INDEX_HOST points to a 1024-dim index")
        raise HTTPException(status_code=500, detail=f"Failed to store text: {err}")

    await _reprompt_after_change(tenant)
    return {"status": "ok", "vectors_stored": vectors}


@router.get("/files/{tenant_id}")
async def list_files(
    tenant_id: str,
    authorization: Annotated[str | None, Header()] = None,
):
    await verify_tenant_owner(tenant_id, authorization)
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Tenant lookup failed")
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"files": tenant.get("kb_files") or []}


@router.post("/repair-prompt/{tenant_id}")
async def repair_prompt(
    tenant_id: str,
    authorization: Annotated[str | None, Header()] = None,
):
    await verify_tenant_owner(tenant_id, authorization)
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Tenant lookup failed")
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    try:
        result = await rebuild_and_push_system_prompt(tenant)
        return result
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clear/{tenant_id}")
async def clear_knowledge(
    tenant_id: str,
    authorization: Annotated[str | None, Header()] = None,
):
    await verify_tenant_owner(tenant_id, authorization)
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("Tenant lookup failed for %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Tenant lookup failed")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    namespace: str = tenant["pinecone_namespace"]
    try:
        knowledge.clear_namespace(namespace)
        logger.info("Cleared knowledge base for tenant %s", tenant_id)
        return {"status": "cleared"}
    except Exception as e:
        logger.error("Failed to clear namespace for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to clear knowledge base")
