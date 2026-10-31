"""crawl_website against a fake with the real SDK's signatures.

conftest.py replaces firecrawl with a MagicMock, which accepts any argument. That
is how an unsupported `timeout=` reached production: every crawl raised TypeError
and quietly fell back to the homepage. The fake below copies firecrawl-py 0.0.16
exactly, so a bad call fails here.
"""
from unittest.mock import AsyncMock, patch

import pytest

from services import knowledge

URL = "https://example.com"


def _page(path, text):
    return {"markdown": text, "metadata": {"sourceURL": URL + path, "title": path}}


class FakeFirecrawl:
    def __init__(self, statuses=None, start_error=None):
        self.statuses = list(statuses or [])
        self.start_error = start_error
        self.params = None
        self.polls = 0

    def crawl_url(self, url, params=None, wait_until_done=True, poll_interval=2,
                  idempotency_key=None):
        if self.start_error:
            raise self.start_error
        assert wait_until_done is False, "the SDK's own wait has no time limit"
        self.params = params
        return {"jobId": "job-1"}

    def check_crawl_status(self, job_id):
        assert job_id == "job-1"
        self.polls += 1
        return self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]


async def _crawl(fake, timeout=60):
    with patch.object(knowledge, "FirecrawlApp", return_value=fake), \
         patch.object(knowledge, "FIRECRAWL_API_KEY", "key"), \
         patch.object(knowledge, "CRAWL_POLL_SECONDS", 0), \
         patch.object(knowledge, "CRAWL_TIMEOUT_SECONDS", timeout), \
         patch.object(knowledge, "scrape_website",
                      new=AsyncMock(return_value="homepage only")) as scrape:
        text, meta = await knowledge.crawl_website(URL, max_pages=5)
    return text, meta, scrape


@pytest.mark.asyncio
async def test_returns_every_page_once_the_job_completes():
    fake = FakeFirecrawl([
        {"status": "active", "partial_data": []},
        {"status": "completed", "data": [_page("/", "home"), _page("/pricing", "prices")]},
    ])
    text, meta, scrape = await _crawl(fake)

    assert fake.polls == 2
    assert [m["source_url"] for m in meta] == [URL + "/", URL + "/pricing"]
    assert "home" in text and "prices" in text
    assert fake.params["crawlerOptions"]["limit"] == 5
    scrape.assert_not_called()


@pytest.mark.asyncio
async def test_time_limit_keeps_the_pages_finished_so_far():
    fake = FakeFirecrawl([{"status": "active", "partial_data": [_page("/", "home")]}])
    text, meta, scrape = await _crawl(fake, timeout=0)

    assert len(meta) == 1 and "home" in text
    scrape.assert_not_called()


@pytest.mark.asyncio
async def test_time_limit_with_no_pages_falls_back_to_the_homepage():
    text, _, scrape = await _crawl(FakeFirecrawl([{"status": "active"}]), timeout=0)

    assert text == "homepage only"
    scrape.assert_awaited_once_with(URL)


@pytest.mark.asyncio
async def test_a_failed_job_falls_back_to_the_homepage():
    text, _, _ = await _crawl(FakeFirecrawl([{"status": "failed"}]))
    assert text == "homepage only"


@pytest.mark.asyncio
async def test_a_job_that_cannot_start_falls_back_to_the_homepage():
    text, _, _ = await _crawl(FakeFirecrawl(start_error=RuntimeError("402")))
    assert text == "homepage only"


@pytest.mark.asyncio
async def test_a_completed_job_with_no_pages_falls_back_to_the_homepage():
    text, _, _ = await _crawl(FakeFirecrawl([{"status": "completed", "data": []}]))
    assert text == "homepage only"
