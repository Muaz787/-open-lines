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


async def embed_and_store(namespace: str, text: str, tenant_id: str) -> int:
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
            "id": f"{tenant_id}-{i}",
            "values": embeddings[i],
            "metadata": {"text": chunks[i], "tenant_id": tenant_id},
        }
        for i in range(len(chunks))
    ]

    # Upsert in batches of 100 (Pinecone recommended limit)
    batch_size = 100
    for start in range(0, len(vectors), batch_size):
        index.upsert(vectors=vectors[start : start + batch_size], namespace=namespace)

    logger.info(
        "Stored %d vectors in Pinecone namespace '%s' for tenant %s",
        len(vectors), namespace, tenant_id,
    )
    return len(vectors)


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


async def refresh_tenant_knowledge(
    tenant_id: str, website_url: str, namespace: str
) -> dict:
    raw_text = await scrape_website(website_url)

    # Count pages by splitting on the double-newline separator used in scrape_website
    pages_scraped = raw_text.count("\n\n") + 1 if raw_text.strip() else 0

    vectors_stored = await embed_and_store(namespace, raw_text, tenant_id)

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
