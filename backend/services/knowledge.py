import os
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from firecrawl import FirecrawlApp
from openai import AsyncOpenAI
from pinecone import Pinecone

load_dotenv()

logger = logging.getLogger(__name__)

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME")
PINECONE_INDEX_HOST = os.getenv("PINECONE_INDEX_HOST")

CHUNK_TOKENS = 500
OVERLAP_TOKENS = 50
# Approximation: 1 token ≈ 4 characters
CHARS_PER_TOKEN = 4

_openai: AsyncOpenAI | None = None
_pinecone_index = None


def _get_openai() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY must be set")
        _openai = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _openai


def _get_pinecone_index():
    global _pinecone_index
    if _pinecone_index is None:
        if not PINECONE_API_KEY:
            raise RuntimeError("PINECONE_API_KEY must be set")
        if not PINECONE_INDEX_NAME and not PINECONE_INDEX_HOST:
            raise RuntimeError("PINECONE_INDEX_NAME or PINECONE_INDEX_HOST must be set")
        pc = Pinecone(api_key=PINECONE_API_KEY)
        if PINECONE_INDEX_HOST:
            # Strip scheme — pinecone-client 3.x adds https:// internally
            host = PINECONE_INDEX_HOST.removeprefix("https://").removeprefix("http://")
            _pinecone_index = pc.Index(host=host)
        else:
            _pinecone_index = pc.Index(PINECONE_INDEX_NAME)
    return _pinecone_index


def _chunk_text(text: str) -> list[str]:
    chunk_chars = CHUNK_TOKENS * CHARS_PER_TOKEN
    overlap_chars = OVERLAP_TOKENS * CHARS_PER_TOKEN
    step = chunk_chars - overlap_chars
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + chunk_chars])
        start += step
    return chunks


async def scrape_website(url: str) -> str:
    if not FIRECRAWL_API_KEY:
        raise RuntimeError("FIRECRAWL_API_KEY must be set")
    app = FirecrawlApp(api_key=FIRECRAWL_API_KEY)
    result = app.scrape_url(url, params={"formats": ["markdown"]})
    # SDK may return a dict or an object with attribute access
    if isinstance(result, dict):
        text = result.get("markdown") or result.get("content", "")
    else:
        text = getattr(result, "markdown", None) or getattr(result, "content", "") or ""
    logger.info("Scraped %d chars from %s", len(text), url)
    return text


async def embed_and_store(
    namespace: str,
    text: str,
    tenant_id: str,
    source_id: str | None = None,
    source_type: str | None = None,
) -> int:
    """Embed `text` and upsert into Pinecone. `source_type` ('website' | 'file' |
    'text') tags every vector so website content can later be cleared without
    touching uploaded documents."""
    chunks = _chunk_text(text)
    if not chunks:
        logger.warning("No chunks produced for tenant %s", tenant_id)
        return 0

    openai = _get_openai()
    index = _get_pinecone_index()

    response = await openai.embeddings.create(
        model="text-embedding-3-small",
        input=chunks,
        dimensions=1024,
    )
    embeddings = [item.embedding for item in response.data]

    vectors = [
        {
            "id": f"{source_id}-{i}" if source_id else f"{tenant_id}-{i}",
            "values": embeddings[i],
            "metadata": {
                "text": chunks[i],
                "tenant_id": tenant_id,
                **({"source_id": source_id} if source_id else {}),
                **({"source_type": source_type} if source_type else {}),
            },
        }
        for i in range(len(chunks))
    ]

    batch_size = 100
    for start in range(0, len(vectors), batch_size):
        index.upsert(vectors=vectors[start : start + batch_size], namespace=namespace)

    logger.info(
        "Stored %d vectors in Pinecone namespace '%s' for tenant %s (source=%s, type=%s)",
        len(vectors), namespace, tenant_id, source_id or "none", source_type or "none",
    )
    return len(vectors)


def delete_by_source(namespace: str, source_id: str) -> None:
    index = _get_pinecone_index()
    index.delete(filter={"source_id": source_id}, namespace=namespace)
    logger.info("Deleted vectors for source %s in namespace '%s'", source_id, namespace)


def delete_old_website_vectors(namespace: str, keep_source_id: str) -> None:
    """Delete website vectors from EARLIER crawl generations, keeping only the
    just-written generation (`keep_source_id`). Never touches file/text vectors
    (different source_type). Safe failure mode: leaves duplicates, never empties."""
    index = _get_pinecone_index()
    index.delete(
        filter={"source_type": "website", "source_id": {"$ne": keep_source_id}},
        namespace=namespace,
    )


def delete_legacy_website_vectors(namespace: str, slug_or_tenant_ids: list[str]) -> None:
    """One-time cleanup of pre-tagging website vectors. Those used ids of the form
    `{tenant_id}-{i}` / `{slug}-{i}` with NO source_type, so they can't be reached
    by a metadata filter. Uploaded-document vectors use a UUID source_id prefix, so
    deleting these exact id ranges can never hit a document vector."""
    index = _get_pinecone_index()
    ids: list[str] = []
    for base in slug_or_tenant_ids:
        if base:
            ids.extend(f"{base}-{i}" for i in range(0, 1500))
    for start in range(0, len(ids), 1000):
        try:
            index.delete(ids=ids[start : start + 1000], namespace=namespace)
        except Exception as e:
            logger.warning("Legacy website vector cleanup batch failed for '%s': %s", namespace, e)
            return


def extract_text(filename: str, content: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        return _extract_pdf(content)
    elif name.endswith(".docx"):
        return _extract_docx(content)
    elif name.endswith(".xlsx") or name.endswith(".xls"):
        return _extract_xlsx(content)
    elif name.endswith((".txt", ".md", ".csv")):
        return content.decode("utf-8", errors="ignore")
    else:
        ext = name.rsplit(".", 1)[-1] if "." in name else "unknown"
        raise ValueError(f"Unsupported file type .{ext}. Accepted: PDF, Word (.docx), Excel (.xlsx/.xls), plain text (.txt/.csv/.md)")


def _extract_pdf(content: bytes) -> str:
    import io
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(p for p in pages if p.strip())


def _extract_docx(content: bytes) -> str:
    import io
    from docx import Document
    doc = Document(io.BytesIO(content))
    parts: list[str] = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n\n".join(parts)


def _extract_xlsx(content: bytes) -> str:
    import io
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    rows: list[str] = []
    for sheet in wb.worksheets:
        rows.append(f"[Sheet: {sheet.title}]")
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                rows.append(" | ".join(cells))
    wb.close()
    return "\n".join(rows)


async def query_knowledge_base(namespace: str, query: str, top_k: int = 5) -> str:
    openai = _get_openai()
    index = _get_pinecone_index()

    response = await openai.embeddings.create(
        model="text-embedding-3-small",
        input=[query],
        dimensions=1024,
    )
    query_vector = response.data[0].embedding

    results = index.query(
        vector=query_vector,
        top_k=top_k,
        namespace=namespace,
        include_metadata=True,
    )

    matches = results.get("matches", [])
    texts = [m["metadata"]["text"] for m in matches if m.get("metadata", {}).get("text")]
    return "\n\n".join(texts)


def clear_namespace(namespace: str) -> None:
    index = _get_pinecone_index()
    index.delete(delete_all=True, namespace=namespace)
    logger.info("Cleared Pinecone namespace '%s'", namespace)


MAX_SCRAPE_CHARS = 200_000  # cap embedding cost per crawl (scrape is single-page)


async def refresh_tenant_knowledge(
    tenant_id: str, website_url: str, namespace: str
) -> dict:
    """Two-phase, safe website refresh:
      1. Scrape first — if it fails or returns nothing, raise, so the caller keeps
         the existing knowledge base rather than emptying it.
      2. Embed the NEW crawl generation, THEN delete older website generations
         (and pre-tagging legacy website vectors). Cleanup runs only after the new
         content is in place, so a failure leaves duplicates — never an empty KB —
         and uploaded-document vectors are never touched.
    """
    import time

    # Phase 1 — scrape (most likely failure point: network / Firecrawl).
    raw_text = await scrape_website(website_url)
    if not raw_text or not raw_text.strip():
        raise ValueError("Website scrape returned no content")
    raw_text = raw_text[:MAX_SCRAPE_CHARS]
    pages_scraped = raw_text.count("\n\n") + 1

    # Phase 2 — write the new generation under a unique website source id.
    gen_source_id = f"website-{int(time.time())}"
    vectors_stored = await embed_and_store(
        namespace, raw_text, tenant_id, source_id=gen_source_id, source_type="website"
    )

    # Remove previous website generations + legacy untagged website vectors.
    try:
        delete_old_website_vectors(namespace, keep_source_id=gen_source_id)
        delete_legacy_website_vectors(namespace, list({namespace, tenant_id}))
    except Exception as e:
        logger.warning("Old website vector cleanup failed for tenant %s (non-fatal): %s", tenant_id, e)

    refreshed_at = datetime.now(timezone.utc)
    logger.info(
        "Knowledge refresh complete for tenant %s: %d pages, %d vectors",
        tenant_id, pages_scraped, vectors_stored,
    )
    return {
        "pages_scraped": pages_scraped,
        "vectors_stored": vectors_stored,
        "refreshed_at": refreshed_at,
    }
