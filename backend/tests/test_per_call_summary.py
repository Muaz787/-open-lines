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


# ── behaviour: two calls from one caller, processed end to end ────────────────

TENANT = {"id": "t1", "business_name": "Open Lines", "calendar_timezone": "America/Toronto"}
CALLER = "+16475550100"


class Store:
    """calls and leads, as the processor writes them."""

    def __init__(self, analyses):
        self.analyses = analyses          # transcript -> analysis
        self.calls: dict[str, dict] = {}
        self.leads: dict[str, dict] = {}

    async def get_lead_by_phone(self, tid, phone):
        return next((dict(l) for l in self.leads.values() if l["phone"] == phone), None)

    async def insert_lead(self, tid, data):
        lid = f"lead-{len(self.leads) + 1}"
        self.leads[lid] = {"id": lid, "tenant_id": tid, **data}
        return dict(self.leads[lid])

    async def update_lead(self, tid, lid, data):
        self.leads[lid].update(data)

    async def insert_call(self, tid, lid, data):
        cid = f"call-{len(self.calls) + 1}"
        self.calls[cid] = {"id": cid, "tenant_id": tid, "lead_id": lid, **data}
        return dict(self.calls[cid])

    async def update_call(self, cid, data):
        self.calls[cid].update(data)
        return dict(self.calls[cid])

    async def analyze(self, transcript, tenant):
        return dict(self.analyses[transcript])

    async def calls_with_leads(self, tid, since=None, limit=100):
        """What get_calls_with_leads selects: the call's own columns, lead identity."""
        cols = ("id", "vapi_call_id", "duration_secs", "created_at", "lead_id", "disposition",
                "transferred", "summary", "urgency", "key_details", "suggested_next_step")
        out = []
        for c in self.calls.values():
            lead = self.leads[c["lead_id"]]
            out.append({**{k: c.get(k) for k in cols},
                        "leads": {"name": lead.get("name"), "phone": lead.get("phone")}})
        return sorted(out, key=lambda r: r["created_at"], reverse=True)

    def __enter__(self):
        self._p = [
            patch("db.supabase.get_tenant_by_phone", new=AsyncMock(return_value=TENANT)),
            patch("db.supabase.get_lead_by_phone", new=AsyncMock(side_effect=self.get_lead_by_phone)),
            patch("db.supabase.insert_lead", new=AsyncMock(side_effect=self.insert_lead)),
            patch("db.supabase.update_lead", new=AsyncMock(side_effect=self.update_lead)),
            patch("db.supabase.insert_call", new=AsyncMock(side_effect=self.insert_call)),
            patch("db.supabase.update_call", new=AsyncMock(side_effect=self.update_call)),
            patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=TENANT)),
            patch("db.supabase.get_calls_with_leads", new=AsyncMock(side_effect=self.calls_with_leads)),
            patch("db.routing.get_transfer_attempt", new=AsyncMock(return_value=None)),
            patch("services.call_enrichment.analyze_transcript", new=AsyncMock(side_effect=self.analyze)),
            patch("services.analytics.capture"),
            patch("services.zapier.emit", new=AsyncMock()),
            patch("services.webhook_processor._dispatch_call_summary", new=AsyncMock()),
        ]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self._p:
            p.stop()

    @staticmethod
    async def call(vapi_id, transcript, created_at):
        await webhook_processor.process_end_of_call({"message": {
            "type": "end-of-call-report", "transcript": transcript,
            "call": {"id": vapi_id, "customer": {"number": CALLER}},
            "phoneNumber": {"number": "+14385550000"}}})
        return created_at


FIRST = "AI: Hello. User: Can I book a demo for Thursday at nine please?"
SECOND = "AI: Hello. User: Actually I'd like to ask about pricing for two locations."
SHORT = "User: hi"               # too short to analyse


ANALYSES = {
    FIRST: {"summary": "Booked a demo for Thursday at 9.", "urgency": "hot",
            "key_details": {"service": "demo"}, "suggested_next_step": "Send the deck",
            "caller_name": "Sam"},
    SECOND: {"summary": "Asked about pricing for two locations.", "urgency": "warm",
             "key_details": {"locations": "2"}, "suggested_next_step": "Quote Business plan",
             "caller_name": "Sam"},
}


async def _three_calls(store):
    await store.call("v1", FIRST, "1")
    await store.call("v2", SECOND, "2")
    await store.call("v3", SHORT, "3")
    for cid, at in zip(("call-1", "call-2", "call-3"), ("2026-11-02T13:39:00+00:00",
                                                      "2026-11-02T23:09:00+00:00",
                                                      "2026-11-02T23:30:00+00:00")):
        store.calls[cid]["created_at"] = at


async def test_two_calls_from_one_caller_keep_their_own_summary_and_rating():
    with Store(ANALYSES) as s:
        await _three_calls(s)
    first, second, short = s.calls["call-1"], s.calls["call-2"], s.calls["call-3"]
    assert len(s.leads) == 1 and first["lead_id"] == second["lead_id"] == short["lead_id"]
    assert (first["summary"], first["urgency"]) == ("Booked a demo for Thursday at 9.", "hot")
    assert first["key_details"] == {"service": "demo"} and first["suggested_next_step"] == "Send the deck"
    assert (second["summary"], second["urgency"]) == ("Asked about pricing for two locations.", "warm")
    # the lead follows the newest ANALYSED call: the short hang-up after it doesn't blank it
    assert s.leads["lead-1"]["summary"] == "Asked about pricing for two locations."
    assert s.leads["lead-1"]["urgency"] == "warm"
    assert s.leads["lead-1"]["status"] == "contacted"


async def test_a_call_without_analysis_stores_nothing_rather_than_the_leads():
    with Store(ANALYSES) as s:
        await _three_calls(s)
    short = s.calls["call-3"]
    assert short.get("summary") is None and short.get("urgency") is None
    assert short.get("key_details") is None and short.get("suggested_next_step") is None


async def test_the_calls_list_and_breakdown_show_each_call_independently():
    with Store(ANALYSES) as s:
        await _three_calls(s)
        listed = await calls_router.list_calls("t1", days=0)
        breakdown = await calls_router.get_analytics("t1", days=0)
    by_id = {r["vapi_call_id"]: r for r in listed}
    assert by_id["v1"]["summary"] == "Booked a demo for Thursday at 9." and by_id["v1"]["urgency"] == "hot"
    assert by_id["v2"]["summary"] == "Asked about pricing for two locations." and by_id["v2"]["urgency"] == "warm"
    assert by_id["v3"]["summary"] is None and by_id["v3"]["urgency"] is None
    assert all(set(r["leads"]) == {"name", "phone"} for r in listed), "lead join is identity only"
    assert breakdown["urgency_breakdown"] == {"hot": 1, "warm": 1, "cold": 0, "unknown": 1}
