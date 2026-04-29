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
        if not PINECONE_INDEX_NAME:
            raise RuntimeError("PINECONE_INDEX_NAME must be set")
        pc = Pinecone(api_key=PINECONE_API_KEY)
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
    result = app.crawl_url(
        url,
        params={
            "limit": 20,
            "scrapeOptions": {"formats": ["markdown"]},
        },
    )
    pages = result.get("data", [])
    logger.info("Scraped %d pages from %s", len(pages), url)
    texts = [
        page.get("markdown", "") or page.get("content", "")
        for page in pages
        if page.get("markdown") or page.get("content")
    ]
    return "\n\n".join(texts)


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


async def query_knowledge_base(namespace: str, query: str, top_k: int = 5) -> str:
    openai = _get_openai()
    index = _get_pinecone_index()

    response = await openai.embeddings.create(
        model="text-embedding-3-small",
        input=[query],
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
