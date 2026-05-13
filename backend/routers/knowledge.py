import logging
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from db import supabase as db
from services import knowledge
from services.provisioning import rebuild_and_push_system_prompt

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
async def update_website_url(tenant_id: str, body: WebsiteRequest):
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
):
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
            vectors = await knowledge.embed_and_store(namespace, text, tenant_id)
            results.append({"file": fname, "status": "ok", "vectors_stored": vectors})
            logger.info("Uploaded %s for tenant %s → %d vectors", fname, tenant_id, vectors)
        except Exception as e:
            logger.error("Failed to embed %s for tenant %s: %s", fname, tenant_id, e)
            results.append({"file": fname, "status": "error", "reason": "embedding failed"})

    if any(r["status"] == "ok" for r in results):
        await _reprompt_after_change(tenant)

    return {"tenant_id": tenant_id, "results": results}


@router.post("/text/{tenant_id}")
async def add_text(tenant_id: str, body: TextRequest):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text cannot be empty")

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
        logger.error("Failed to embed text for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to store text")

    await _reprompt_after_change(tenant)
    return {"status": "ok", "vectors_stored": vectors}


@router.post("/clear/{tenant_id}")
async def clear_knowledge(tenant_id: str):
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
