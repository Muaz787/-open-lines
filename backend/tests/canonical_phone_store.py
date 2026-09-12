"""A tiny in-memory stand-in for the canonical phone table, for release tests.

WHY THIS EXISTS, AND WHAT IT DELIBERATELY DOES NOT DO
conftest stubs Supabase with a MagicMock, which is TRUTHY: every canonical
lookup "finds" a mock row and every fenced write "changes" one. Tests written
against that prove nothing about release, so the canonical world has to be
stated explicitly.

This store implements the DATABASE's side of the contract -- the WHERE clauses
of the fenced update and the status predicates of the two finders -- and nothing
of phone_registry.mark_released's own logic. That distinction is the point: a
fake that decided for itself when a release is idempotent or stale would make
those tests pass against the fake instead of the code. The decisions stay in the
module under test; this only answers "which rows does that query match".

The same invariants are proved against real PostgreSQL in
scripts/verify_027/stage_o_release.py, because a hand-written WHERE clause is
exactly the kind of thing that can be faithful to what I believed and wrong
about what Postgres does.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

from services import phone_lifecycle as lifecycle


def row(**over):
    """A canonical permanent row, live and fully identified."""
    return {
        "id": "row1", "tenant_id": "t1", "e164": "+14165550100",
        "purpose": lifecycle.PURPOSE_PERMANENT, "status": lifecycle.STATUS_ACTIVE,
        "provider": "twilio", "provider_account_sid": "AC_sub",
        "provider_sid": "PN_num1", "iso_country": "CA",
        "released_at": None, "last_error": None,
        **over,
    }


class Store:
    def __init__(self, rows, scalars=None):
        self.rows = [dict(r) for r in rows]
        # tenant_id -> the legacy scalar currently on that tenant row
        self.scalars = dict(scalars or {})
        self.cleared: list[tuple] = []

    # --- db.phone_numbers ---------------------------------------------------
    async def find_owned_by_e164(self, e164):
        for r in self.rows:
            if r["e164"] == e164 and r["status"] in lifecycle.OWNED_E164_STATUSES:
                return dict(r)
        return None

    async def get_current_permanent(self, tenant_id):
        for r in self.rows:
            if (r["tenant_id"] == tenant_id
                    and r["purpose"] == lifecycle.PURPOSE_PERMANENT
                    and r["status"] in lifecycle.CURRENT_PERMANENT_STATUSES):
                return dict(r)
        return None

    async def get_by_id(self, number_id):
        for r in self.rows:
            if r["id"] == number_id:
                return dict(r)
        return None

    async def release_number_cas(self, *, number_id, tenant_id, e164, provider_sid,
                                 provider_account_sid, last_error=""):
        """Every .eq() in the real query, as an AND. Nothing else."""
        out = []
        for r in self.rows:
            if (r["id"] == number_id
                    and r["tenant_id"] == tenant_id
                    and r["e164"] == e164
                    and (r.get("provider_account_sid") or "") == provider_account_sid
                    and (r.get("provider_sid") or "") == provider_sid
                    and r["status"] in lifecycle.RELEASABLE_STATUSES):
                r["status"] = lifecycle.STATUS_RELEASED
                r["released_at"] = datetime.now(timezone.utc).isoformat()
                if last_error:
                    r["last_error"] = last_error[:500]
                out.append(dict(r))
        return out

    # --- db.supabase --------------------------------------------------------
    async def clear_tenant_number_fenced(self, tenant_id, e164, released_at):
        if self.scalars.get(tenant_id) != e164:
            return []
        self.scalars[tenant_id] = None
        self.cleared.append((tenant_id, e164, released_at))
        return [{"id": tenant_id, "twilio_phone_number": None,
                 "vapi_phone_number_id": None, "number_released_at": released_at}]


@contextmanager
def canonical(rows=(), scalars=None):
    """Patch the repository layer onto an explicit in-memory world."""
    st = Store(rows, scalars)
    with patch("db.phone_numbers.find_owned_by_e164", new=st.find_owned_by_e164), \
         patch("db.phone_numbers.get_current_permanent", new=st.get_current_permanent), \
         patch("db.phone_numbers.get_by_id", new=st.get_by_id), \
         patch("db.phone_numbers.release_number_cas", new=st.release_number_cas), \
         patch("db.supabase.clear_tenant_number_fenced", new=st.clear_tenant_number_fenced):
        yield st
