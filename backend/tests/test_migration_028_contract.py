"""Schema contract for migration 028 (W9G.1).

The same limitation as 027's contract test applies -- no test database here -- but
028's constraints WERE executed against a real PostgreSQL 15.19 cluster during W9G.1
using the harness in backend/scripts/verify_027/ (14/14 proofs). This file is the
regression guard that keeps the DDL declaring what those proofs verified.
"""
import re
from pathlib import Path

import pytest

MIGRATION = (Path(__file__).resolve().parents[2]
             / "migrations" / "028_regulatory_requirement_durability.sql")


def _strip_comments(text: str) -> str:
    out = []
    for line in text.splitlines():
        code = line.split("--", 1)[0].rstrip()
        if code.strip():
            out.append(code)
    return "\n".join(out)


@pytest.fixture(scope="module")
def raw() -> str:
    assert MIGRATION.exists(), f"missing migration: {MIGRATION}"
    return MIGRATION.read_text()


@pytest.fixture(scope="module")
def sql(raw) -> str:
    body = _strip_comments(raw).lower()
    body = re.sub(r"comment on (?:table|column)\b.*?;", " ", body, flags=re.S)
    return re.sub(r"\s+", " ", body)


# ── additive, idempotent, dark ──────────────────────────────────────────────

def test_it_is_additive_and_idempotent(sql):
    assert "add column if not exists requirements_fingerprint text null" in sql
    assert "add column if not exists requirements_observed_at timestamptz null" in sql
    assert "create table if not exists tenant_regulatory_business_details (" in sql
    assert sql.count("create table") == 1


def test_nothing_is_dropped_or_retyped(sql):
    for forbidden in ("drop table", "drop column", "drop index", "drop constraint",
                      "alter column", "rename to", "truncate"):
        assert forbidden not in sql


def test_it_writes_no_rows(sql):
    assert "insert into" not in sql
    assert not re.search(r"\bupdate\s+\w+\s+set\b", sql)
    assert "delete from" not in sql


def test_only_the_expected_tables_are_altered(sql):
    assert set(re.findall(r"alter table (\w+)", sql)) == {
        "tenant_regulatory_profiles", "tenant_regulatory_business_details"}


# ── the drift fix ──────────────────────────────────────────────────────────

def test_the_fingerprint_is_shape_checked(sql):
    assert ("constraint trp_requirements_fingerprint_chk check "
            "(requirements_fingerprint is null or requirements_fingerprint ~ "
            "'^[0-9a-f]{64}$')") in sql


def test_a_submitted_profile_must_carry_a_fingerprint(sql):
    """Without one there is nothing to compare the live requirements against, so
    drift cannot be detected."""
    m = re.search(r"constraint trp_submitted_requirements_chk check \(state not in "
                  r"\((.*?)\) or requirements_fingerprint is not null\)", sql)
    assert m
    guarded = {v.strip().strip("'") for v in m.group(1).split(",")}
    assert guarded == {"pending_review", "more_information_required", "approved",
                       "rejected", "number_provisioning", "active"}


# ── the details table ──────────────────────────────────────────────────────

def test_one_row_per_tenant_country_and_end_user_type(sql):
    assert ("trbd_scope_key on tenant_regulatory_business_details "
            "(tenant_id, iso_country, end_user_type)") in sql


def test_the_declaration_columns_are_nullable_and_never_defaulted(sql):
    """A default here would be a guessed statement to a regulator."""
    assert "business_identity text null" in sql
    assert "is_subassigned text null" in sql
    assert "business_identity text not null" not in sql
    assert "default 'direct_customer'" not in sql
    assert "default 'no'" not in sql


def test_only_the_providers_own_enumerated_values_are_accepted(sql):
    assert ("constraint trbd_business_identity_chk check (business_identity is null "
            "or business_identity in ('direct_customer', "
            "'independent_software_vendor'))") in sql
    assert ("constraint trbd_is_subassigned_chk check (is_subassigned is null "
            "or is_subassigned in ('yes', 'no'))") in sql


def test_the_columns_are_named_not_a_blob(sql):
    """A JSON bag would let personal data accumulate in untyped storage nobody
    reviewed."""
    details = sql.split("create table if not exists tenant_regulatory_business_details")[1]
    details = details.split(");")[0]
    for forbidden in ("jsonb", "json ", "raw", "attributes", "payload", "blob"):
        assert forbidden not in details, forbidden
    for expected in ("business_name text null", "business_registration_number text null",
                     "authorized_rep_first_name text null",
                     "authorized_rep_email text null"):
        assert expected in details


def test_it_cascades_with_the_tenant(sql):
    assert "tenant_id uuid not null references tenants(id) on delete cascade" in sql


def test_rls_is_enabled_with_no_policies(sql):
    assert "alter table tenant_regulatory_business_details enable row level security" in sql
    assert "create policy" not in sql
    assert "to anon" not in sql
    assert "grant " not in sql


def test_no_credential_or_token_column_exists(sql):
    for forbidden in ("auth_token", "access_token", "secret", "api_key"):
        assert forbidden not in sql


def test_rollback_is_commented_out(raw):
    body = _strip_comments(raw).lower()
    assert "drop table if exists tenant_regulatory_business_details" not in body
    assert "-- drop table if exists tenant_regulatory_business_details" in raw.lower()
