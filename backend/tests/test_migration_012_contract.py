"""
Schema contract for migration 012.

The repository has no test database — conftest stubs Supabase entirely — so the
constraints that make the backfill safe cannot be exercised against real Postgres
here. What CAN be verified is that the migration actually declares them, which is
the failure mode worth catching: a backfill whose idempotency depends on a unique
index that was silently dropped from the DDL during a rewrite.

These assertions are deliberately about invariants, not formatting.
"""
import re
from pathlib import Path

import pytest

MIGRATION = (Path(__file__).resolve().parents[2]
             / "migrations" / "012_multi_location_foundation.sql")


@pytest.fixture(scope="module")
def sql() -> str:
    assert MIGRATION.exists(), f"missing migration: {MIGRATION}"
    return MIGRATION.read_text().lower()


def _strip_comments(text: str) -> str:
    """Only executable SQL. Comments legitimately mention Square by name — including
    trailing ones on a column line, which is why this strips mid-line comments too
    and not just whole comment lines."""
    out = []
    for line in text.splitlines():
        code = line.split("--", 1)[0].rstrip()
        if code.strip():
            out.append(code)
    return "\n".join(out)


# ── the tables exist and are additive ────────────────────────────────────────

def test_creates_both_tables_idempotently(sql):
    assert "create table if not exists tenant_locations" in sql
    assert "create table if not exists location_provider_bindings" in sql


def test_migration_is_purely_additive(sql):
    """W1 must not alter or drop anything that already exists. An `alter table` on
    a live table is exactly the class of change this workstream promised not to make."""
    body = _strip_comments(sql)
    assert "alter table tenants" not in body
    assert "drop table" not in body
    assert "drop column" not in body
    # The only permitted alters are RLS on the two brand-new tables.
    alters = re.findall(r"alter table (\w+)", body)
    assert set(alters) <= {"tenant_locations", "location_provider_bindings"}


def test_migration_writes_no_rows(sql):
    """The backfill lives in Python so the test suite can reach it. If an insert or
    update appears here there are two implementations of the same logic, and only
    one of them is tested."""
    body = _strip_comments(sql)
    assert "insert into" not in body
    assert not re.search(r"\bupdate\s+tenants\b", body)


# ── the constraints the backfill's idempotency rests on ──────────────────────

def test_one_default_location_per_tenant_is_enforced_by_the_database(sql):
    """The partial unique index is what turns 'the code checks first' into a
    guarantee — a concurrent second run loses at the database instead of creating
    a second default."""
    assert re.search(
        r"create unique index if not exists tenant_locations_one_default_idx\s+"
        r"on tenant_locations \(tenant_id\) where is_default", sql)


def test_slug_is_unique_per_tenant(sql):
    assert re.search(
        r"create unique index if not exists tenant_locations_tenant_slug_idx\s+"
        r"on tenant_locations \(tenant_id, slug\)", sql)


def test_provider_location_is_unique_per_tenant_and_provider(sql):
    assert re.search(
        r"create unique index if not exists lpb_tenant_provider_location_idx\s+"
        r"on location_provider_bindings \(tenant_id, provider, provider_location_id\)", sql)


def test_one_binding_per_location_per_provider(sql):
    assert "lpb_location_provider_idx" in sql
    assert re.search(
        r"on location_provider_bindings \(tenant_location_id, provider\)\s+"
        r"where tenant_location_id is not null", sql)


# ── referential integrity / cleanup ──────────────────────────────────────────

def test_tenant_deletion_cascades_to_both_tables(sql):
    """services/retention.delete_tenant_data() drops the tenant row and relies on
    cascade for tables outside its explicit PII list, exactly as it already does
    for square_services and routing_destinations. Without these clauses a deleted
    tenant would leave orphaned location rows behind."""
    assert sql.count("references tenants(id) on delete cascade") == 2


def test_bindings_cascade_when_their_location_is_deleted(sql):
    assert "references tenant_locations(id) on delete cascade" in sql


def test_binding_may_exist_before_it_is_mapped(sql):
    """Sync discovers provider locations before a human maps them, so the FK column
    has to be nullable."""
    assert re.search(r"tenant_location_id\s+uuid\s+null\s+references tenant_locations", sql)


# ── provider neutrality ──────────────────────────────────────────────────────

def test_bindings_table_has_no_square_specific_columns(sql):
    """The whole point of the two-table split. If a square_* column appears here,
    the next provider needs a schema change."""
    body = _strip_comments(sql)
    start = body.index("create table if not exists location_provider_bindings")
    ddl = body[start:body.index(");", start)]
    assert "square" not in ddl, "location_provider_bindings must not name a provider"


def test_provider_column_is_free_text_not_an_enum(sql):
    """An enum would need a migration to add Google or Microsoft later."""
    body = _strip_comments(sql)
    assert re.search(r"provider\s+text\s+not null", body)
    assert "create type" not in body


def test_provider_location_id_is_text_not_uuid(sql):
    """Square ids are opaque strings, Google calendar ids are email-like. Anything
    narrower than text would exclude a provider we intend to support."""
    body = _strip_comments(sql)
    assert re.search(r"provider_location_id\s+text\s+not null", body)


# ── rollback ─────────────────────────────────────────────────────────────────

def test_rollback_is_documented_and_commented_out(sql):
    assert "rollback" in sql
    lines = [l.strip() for l in sql.splitlines() if "drop table" in l]
    assert lines, "rollback must name the tables it drops"
    assert all(l.startswith("--") for l in lines), "rollback must not be executable"


def test_rollback_drops_bindings_before_locations(sql):
    """FK order: bindings reference locations."""
    tail = sql[sql.index("rollback"):]
    assert tail.index("drop table if exists location_provider_bindings") < \
           tail.index("drop table if exists tenant_locations")
