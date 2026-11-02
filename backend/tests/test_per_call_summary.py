"""
Each call keeps its own summary and rating.

The analysis of a call was written only to the caller's lead, which the next call
overwrites, and the calls page read it from there. Six calls from one caller all
showed the newest call's summary and a Hot rating, including five- and
twelve-second calls that had no analysis at all.
"""
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from db import supabase
from routers import calls as calls_router
from services import call_enrichment, webhook_processor


def test_call_summary_takes_this_calls_analysis():
    row = call_enrichment.call_summary({
        "summary": " Booked a demo for Nov 4 ", "urgency": "HOT",
        "key_details": {"service": "demo"}, "suggested_next_step": "Send the deck",
        "intent": "booking"})
    assert row == {"summary": "Booked a demo for Nov 4", "urgency": "hot",
                   "key_details": {"service": "demo"}, "suggested_next_step": "Send the deck"}


@pytest.mark.parametrize("analysis", [{}, {"summary": "  ", "urgency": "unknown"}])
def test_nothing_to_say_is_stored_as_missing_not_as_empty(analysis):
    assert call_enrichment.call_summary(analysis) == {
        "summary": None, "urgency": None, "key_details": None, "suggested_next_step": None}


def test_the_processor_writes_the_summary_to_the_call_row():
    src = inspect.getsource(webhook_processor.process_end_of_call)
    assert "call_enrichment.call_summary(analysis)" in src
    # in its own write, so a database without migration 044 keeps the enrichment
    assert src.index("call_enrichment.call_enrichment(analysis)") < src.index(
        "call_enrichment.call_summary(analysis)")


def test_the_calls_list_reads_summary_and_rating_from_the_call_not_the_lead():
    src = inspect.getsource(supabase.get_calls_with_leads)
    assert "summary, urgency, key_details, suggested_next_step" in src
    assert "leads(name, phone)" in src
    assert "leads(name, phone, urgency, summary" not in src
    assert "leads(name, phone, urgency, summary" not in inspect.getsource(supabase.get_call_detail)


async def test_the_rating_breakdown_counts_each_calls_own_rating():
    calls = [
        {"urgency": "hot", "duration_secs": 219, "created_at": "2026-11-02T23:09:47+00:00",
         "leads": {"urgency": "hot"}},
        {"urgency": None, "duration_secs": 5, "created_at": "2026-11-02T20:00:00+00:00",
         "leads": {"urgency": "hot"}},
        {"urgency": "cold", "duration_secs": 12, "created_at": "2026-11-01T20:00:00+00:00",
         "leads": {"urgency": "hot"}},
    ]
    with patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value={"calendar_timezone": "America/Toronto"})), \
            patch("db.supabase.get_calls_with_leads", new=AsyncMock(return_value=calls)):
        out = await calls_router.get_analytics("t1", days=0)
    assert out["urgency_breakdown"] == {"hot": 1, "warm": 0, "cold": 1, "unknown": 1}
