"""
The Supabase client is synchronous. Called directly inside an `async def`, every
.execute() froze the single uvicorn event loop, so a dashboard's parallel
requests -- and Vapi webhooks, and live-call tool calls -- were served one at a
time. These tests pin the fix: blocking calls run on the query pool, and no new
code can put a bare .execute() back inside an async function.
"""
import ast
import asyncio
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from db import supabase as db
from services import security

BACKEND = Path(__file__).resolve().parent.parent
DELAY = 0.3
N = 5


class _SlowQuery:
    """A query builder whose execute() blocks like a real network round-trip."""

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def execute(self):
        time.sleep(DELAY)
        return type("Res", (), {"data": {"id": "t1"}})()


class _SlowClient:
    def table(self, _name):
        return _SlowQuery()

    class auth:  # noqa: N801 -- mirrors client.auth
        @staticmethod
        def get_user(_token):
            time.sleep(DELAY)
            user = type("U", (), {"user_metadata": {"tenant_id": "t1"}})()
            return type("R", (), {"user": user})()


async def _elapsed(coros) -> float:
    start = time.perf_counter()
    await asyncio.gather(*coros)
    return time.perf_counter() - start


async def test_db_queries_run_concurrently():
    with patch.object(db, "get_client", return_value=_SlowClient()):
        elapsed = await _elapsed(db.get_tenant_by_id("t1") for _ in range(N))
    # Serialised on the event loop this would take N * DELAY = 1.5s.
    assert elapsed < DELAY * N / 2, f"queries serialised: {elapsed:.2f}s"


async def test_tenant_auth_check_runs_concurrently():
    with patch.object(db, "get_client", return_value=_SlowClient()):
        elapsed = await _elapsed(
            security.verify_tenant_owner("t1", "Bearer tok") for _ in range(N))
    assert elapsed < DELAY * N / 2, f"auth checks serialised: {elapsed:.2f}s"


async def test_event_loop_stays_responsive_during_a_query():
    """A heartbeat on the loop keeps ticking while a slow query is in flight."""
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    beat = asyncio.create_task(heartbeat())
    try:
        with patch.object(db, "get_client", return_value=_SlowClient()):
            await db.get_tenant_by_id("t1")
    finally:
        beat.cancel()
    assert ticks >= 5, f"event loop was blocked (only {ticks} ticks)"


def _bare_executes_in_async_defs(path: Path) -> list[int]:
    tree = ast.parse(path.read_text())
    hits = []

    def visit(node, in_async):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.AsyncFunctionDef):
                visit(child, True)
            elif isinstance(child, (ast.FunctionDef, ast.Lambda)):
                visit(child, False)
            else:
                if (in_async and isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and child.func.attr == "execute"
                        and not child.args and not child.keywords):
                    hits.append(child.lineno)
                visit(child, in_async)

    visit(tree, False)
    return hits


@pytest.mark.parametrize("folder", ["db", "services", "routers"])
def test_no_blocking_execute_inside_async_functions(folder):
    offenders = {
        str(p.relative_to(BACKEND)): lines
        for p in sorted((BACKEND / folder).rglob("*.py"))
        if (lines := _bare_executes_in_async_defs(p))
    }
    assert not offenders, (
        "Bare .execute() inside async def blocks the event loop; "
        f"use `await run_query(<builder>)` from db.supabase instead: {offenders}")
