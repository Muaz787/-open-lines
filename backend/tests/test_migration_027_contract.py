"""
Schema contract for migration 027 (W9D — regulated phone numbers).

THE LIMITATION, STATED UP FRONT. This repository has no test database: conftest
stubs Supabase entirely, and there is no local Postgres, Docker or pg driver
available. So a partial unique index or a composite foreign key CANNOT be
exercised against real Postgres here, and nothing in this file should be read as
proof that Postgres rejected a bad row. What these tests prove is that migration
027 DECLARES the constraints the application's safety rests on — which is the
failure mode actually worth catching: an invariant quietly dropped from the DDL
during a rewrite, while the code keeps assuming it.

Two things make this stronger than grepping for reassuring words:

  1. Every assertion runs against EXECUTABLE SQL ONLY. The migration's comments
     legitimately discuss tenants.country, provisionally_approved and
     tenant_created_at at length, precisely because it explains why it does NOT
     use them. If prose could satisfy an assertion, the test would pass on an
     explanation of a constraint instead of the constraint.

  2. The index predicates are cross-checked against services/phone_lifecycle.py,
     which is what the application itself reads. A rewrite that widens an index
     without widening the code (or the reverse) fails here rather than in
     production as a 23505.
"""
import re
from pathlib import Path

import pytest

from services import phone_lifecycle as lifecycle

MIGRATION = (Path(__file__).resolve().parents[2]
             / "migrations" / "027_regulated_phone_numbers.sql")

NEW_TABLES = ("tenant_regulatory_addresses", "tenant_regulatory_profiles",
              "tenant_phone_numbers", "tenant_regulatory_events")


def _strip_comments(text: str) -> str:
    """Executable SQL only, including stripping trailing comments on column lines."""
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
    """Lower-cased executable SQL, whitespace-collapsed so a line break inside a
    predicate cannot hide it from a substring assertion.

    `comment on ... ;` statements are stripped too. They are executable, but their
    payload is prose -- and prose is exactly what must not be able to satisfy a
    constraint assertion. Leaving them in would let a sentence about
    tenants.country count as a reference to tenants.country."""
    body = _strip_comments(raw).lower()
    body = re.sub(r"comment on (?:table|column)\b.*?;", " ", body, flags=re.S)
    return re.sub(r"\s+", " ", body)


@pytest.fixture(scope="module")
def rollback_ddl(raw) -> str:
    """Only the commented-out DDL lines of the rollback block, not its prose."""
    tail = raw.lower().split("rollback (do not run")[1]
    return "\n".join(line for line in tail.splitlines()
                     if re.match(r"\s*--\s*(drop|alter|truncate)\b", line))


def _index_predicate(sql: str, index_name: str) -> str:
    """The `where ...` predicate of one index, or '' if it has none."""
    m = re.search(rf"create (?:unique )?index if not exists {index_name}\b(.*?);", sql)
    assert m, f"index {index_name} is not declared"
    body = m.group(1)
    w = re.search(r"\bwhere\b(.*)$", body)
    return (w.group(1).strip() if w else "")


def _in_list(values) -> str:
    """The SQL `in ('a', 'b')` fragment for a tuple of statuses."""
    return "in (" + ", ".join(f"'{v}'" for v in values) + ")"


# ── additive, idempotent, non-destructive, writes nothing ───────────────────

def test_creates_exactly_the_four_new_tables_idempotently(sql):
    for table in NEW_TABLES:
        assert f"create table if not exists {table} (" in sql
    assert sql.count("create table") == len(NEW_TABLES)


def test_every_index_is_idempotent(sql):
    assert "create index " not in sql.replace("create index if not exists ", "")
    assert "create unique index " not in sql.replace(
        "create unique index if not exists ", "")


def test_nothing_is_dropped_or_retyped(sql):
    for forbidden in ("drop table", "drop column", "drop index", "drop constraint",
                      "alter column", "rename to", "truncate"):
        assert forbidden not in sql, f"027 must not {forbidden}"


def test_migration_writes_no_rows(sql):
    """The backfill lives in Python so the test suite can reach it. An insert here
    would be a second implementation of the same logic that no test can run."""
    assert "insert into" not in sql
    assert not re.search(r"\bupdate\s+\w+\s+set\b", sql)
    assert "delete from" not in sql


def test_the_only_alters_are_the_new_column_rls_and_ownership_keys(sql):
    targets = set(re.findall(r"alter table (\w+)", sql))
    assert targets == {"tenants", "tenant_locations"} | set(NEW_TABLES)
    # tenants gains one nullable column and one check, nothing else.
    assert "alter table tenants add column if not exists business_country_code text null" in sql
    assert sql.count("alter table tenants add column") == 1


def test_existing_tables_keep_their_authority(sql):
    """027 must not touch the scalar phone columns it is designed to coexist with."""
    for column in ("twilio_phone_number", "twilio_subaccount_sid", "twilio_auth_token"):
        assert f"alter table tenants add column if not exists {column}" not in sql
        assert f"drop column if exists {column}" not in sql


# ── business country ────────────────────────────────────────────────────────

def test_business_country_code_is_text_with_an_uppercase_iso_check(sql):
    """text + CHECK, not char(2): the repository has no char(n) anywhere."""
    assert "business_country_code text null" in sql
    assert "char(2)" not in sql
    assert ("check (business_country_code is null or business_country_code ~ "
            "'^[a-z]{2}$')" in sql.replace("^[A-Z]{2}$".lower(), "^[a-z]{2}$"))


def test_business_country_code_is_nullable_for_legacy_tenants(sql):
    assert "business_country_code text not null" not in sql


def test_analyzer_country_is_never_referenced_by_executable_sql(sql):
    """tenants.country is discussed at length in the comments and must appear in
    none of the DDL: it is not a compliance authority."""
    assert "tenants.country" not in sql
    assert not re.search(r"\bcountry\b(?!_code)", sql.split("create table")[0])


# ── cross-tenant ownership: composite keys and composite FKs ────────────────

def test_tenant_locations_exposes_the_composite_ownership_key(sql):
    assert ("alter table tenant_locations add constraint "
            "tenant_locations_tenant_id_id_key unique (tenant_id, id)") in sql


@pytest.mark.parametrize("table", NEW_TABLES[:3])
def test_each_owning_table_exposes_its_own_composite_key(sql, table):
    prefix = {"tenant_regulatory_addresses": "tra",
              "tenant_regulatory_profiles": "trp",
              "tenant_phone_numbers": "tpn"}[table]
    assert f"constraint {prefix}_tenant_id_id_key unique (tenant_id, id)" in sql


@pytest.mark.parametrize("name,cols,target", [
    ("tra_location_owner_fk", "(tenant_id, tenant_location_id)",
     "tenant_locations (tenant_id, id)"),
    ("trp_location_owner_fk", "(tenant_id, tenant_location_id)",
     "tenant_locations (tenant_id, id)"),
    ("trp_address_owner_fk", "(tenant_id, regulatory_address_id)",
     "tenant_regulatory_addresses (tenant_id, id)"),
    ("tpn_location_owner_fk", "(tenant_id, tenant_location_id)",
     "tenant_locations (tenant_id, id)"),
    ("tpn_profile_owner_fk", "(tenant_id, regulatory_profile_id)",
     "tenant_regulatory_profiles (tenant_id, id)"),
    ("tre_profile_owner_fk", "(tenant_id, regulatory_profile_id)",
     "tenant_regulatory_profiles (tenant_id, id)"),
])
def test_every_cross_tenant_reference_is_a_composite_foreign_key(sql, name, cols, target):
    """A plain FK to (id) proves the row exists; it does NOT prove it belongs to the
    same tenant. Every one of these references crosses a tenant boundary if it is
    single-column, so every one of them is composite."""
    assert f"constraint {name} foreign key {cols} references {target}" in sql


def test_no_single_column_fk_to_an_owned_table(sql):
    """The regression this guards: someone 'simplifying' a composite FK back to
    references tenant_regulatory_addresses(id)."""
    for target in ("tenant_locations(id)", "tenant_locations (id)",
                   "tenant_regulatory_addresses(id)", "tenant_regulatory_addresses (id)",
                   "tenant_regulatory_profiles(id)", "tenant_regulatory_profiles (id)"):
        assert f"references {target}" not in sql


def test_an_event_naming_a_profile_must_also_name_its_tenant(sql):
    """MATCH SIMPLE skips a composite FK when any key column is NULL, so without
    this CHECK an event could carry tenant A and tenant B's profile unchecked."""
    assert ("constraint tre_profile_needs_tenant_chk check (regulatory_profile_id "
            "is null or tenant_id is not null)") in sql


def test_both_event_owner_fks_cascade_rather_than_set_null(sql):
    """MEASURED ON REAL POSTGRES, NOT REASONED ABOUT (W9E Stage E).

    An earlier draft used ON DELETE SET NULL so a deleted profile would leave a
    de-owned audit row. Executing it on PostgreSQL 15.19 disproved the design:
    deleting a TENANT fires the tenant_id FK first, nulling tenant_id while
    regulatory_profile_id is still set, which trips tre_profile_needs_tenant_chk --
    making tenant deletion (account closure, GDPR erasure) impossible.

    CASCADE on both is deterministic, keeps the CHECK that closes the MATCH SIMPLE
    hole, and does not retain FailureReason text about a deleted customer."""
    assert re.search(r"constraint tre_profile_owner_fk foreign key \(tenant_id, "
                     r"regulatory_profile_id\) references tenant_regulatory_profiles "
                     r"\(tenant_id, id\) on delete cascade", sql)
    assert "on delete set null" not in sql, (
        "a SET NULL owner action on the event ledger reintroduces the tenant-delete "
        "deadlock W9E measured")
    events = sql.split("create table if not exists tenant_regulatory_events")[1]
    assert "tenant_id uuid null references tenants(id) on delete cascade" in events


# ── locality is metadata, never identity ───────────────────────────────────

def test_no_locality_scope_key_column_survives(sql):
    """W9C proposed regulatory_scope_key as locality text. Twilio's search locality
    is not the locality an address must satisfy, and provider normalisation rewrites
    the string, so locality text cannot be a durable key."""
    assert "regulatory_scope_key" not in sql


def test_provider_locality_is_not_part_of_any_key(sql):
    """It may be stored. It may not be keyed on."""
    assert "provider_locality text null" in sql
    for m in re.finditer(r"create unique index if not exists (\w+)(.*?);", sql):
        assert "locality" not in m.group(2), f"{m.group(1)} keys on locality"


def test_profile_identity_is_the_regulatory_address(sql):
    """Two partial unique indexes, split on NULL, rather than one index over a magic
    empty-string scope key."""
    country_wide = _index_predicate(sql, "trp_country_scope_key")
    address_scoped = _index_predicate(sql, "trp_address_scope_key")
    assert country_wide == "regulatory_address_id is null"
    assert address_scoped == "regulatory_address_id is not null"
    assert ("trp_country_scope_key on tenant_regulatory_profiles (tenant_id, "
            "iso_country, number_type, end_user_type)") in sql
    assert ("trp_address_scope_key on tenant_regulatory_profiles (tenant_id, "
            "iso_country, number_type, end_user_type, regulatory_address_id)") in sql


# ── regulatory address cardinality ─────────────────────────────────────────

def test_address_identity_is_the_business_location_not_the_city(sql):
    """A tenant may hold two Dublin premises with different Eircodes. Nothing keys
    on the city, so both can exist."""
    assert (_index_predicate(sql, "tra_location_scope_key")
            == "tenant_location_id is not null")
    assert (_index_predicate(sql, "tra_tenant_scope_key")
            == "tenant_location_id is null")
    assert ("tra_location_scope_key on tenant_regulatory_addresses (tenant_id, "
            "provider, iso_country, tenant_location_id)") in sql
    assert ("tra_tenant_scope_key on tenant_regulatory_addresses (tenant_id, "
            "provider, iso_country)") in sql


def test_provider_sids_are_unique_within_their_account_not_globally(sql):
    """A SID's namespace is the Twilio account that holds it -- proven in W9C, where
    a parent bundle SID was 'not found' under sub-account credentials."""
    for name in ("tra_address_sid_key", "tra_document_sid_key"):
        m = re.search(rf"{name} on tenant_regulatory_addresses \(([^)]*)\)", sql)
        assert m and m.group(1).startswith("provider, provider_account_sid"), name


def test_a_validated_address_must_name_its_provider_object(sql):
    assert ("constraint tra_validated_identity_chk check ( validated is false or "
            "(address_sid is not null and provider_account_sid is not null))") in sql


def test_draft_regulatory_rows_do_not_require_sids(sql):
    """Requirements land on validated/submitted rows only -- a draft has nothing at
    the provider yet."""
    assert "address_sid text null" in sql
    assert "bundle_sid text null" in sql
    assert "end_user_sid text null" in sql


# ── provider state vs our state ────────────────────────────────────────────

def test_provisionally_approved_is_not_one_of_our_states(sql):
    """The SDK has the enum; Twilio's documented status table does not list it; a
    purchase rejection read 'status is not twilio-approved'. An undocumented enum
    name is not a licence to provision, so it lives in bundle_status only."""
    state_check = re.search(r"constraint trp_state_chk check \(state in \((.*?)\)\)", sql)
    assert state_check
    assert "provisionally_approved" not in state_check.group(1)
    assert "'pending_review'" in state_check.group(1)
    assert "'approved'" in state_check.group(1)


def test_bundle_status_is_a_separate_verbatim_column(sql):
    assert "bundle_status text null" in sql
    assert "state text not null default 'not_started'" in sql


def test_a_submitted_profile_must_name_its_bundle(sql):
    assert "constraint trp_submitted_identity_chk check ( state not in (" in sql
    assert "or bundle_sid is not null)" in sql


def test_one_bundle_sid_resolves_to_one_profile(sql):
    """What makes the status callback safe: the tenant is looked up FROM the bundle
    sid, never from anything the caller sends."""
    assert ("trp_bundle_sid_key on tenant_regulatory_profiles (bundle_sid) "
            "where bundle_sid is not null") in sql


# ── phone lifecycle: the DDL and the code must agree ───────────────────────

def test_purpose_and_status_are_separate_columns(sql):
    assert "purpose text not null," in sql
    assert "status text not null," in sql
    assert f"check (purpose {_in_list(lifecycle.PURPOSES[::-1])})" in sql or \
           f"check (purpose {_in_list(lifecycle.PURPOSES)})" in sql
    assert "'primary_active'" not in sql, "role/status conflation has returned"
    assert "'permanent_pending'" not in sql


def test_status_check_matches_the_code(sql):
    m = re.search(r"constraint tpn_status_chk check \(status in \((.*?)\)\)", sql)
    assert m
    declared = {v.strip().strip("'") for v in m.group(1).split(",")}
    assert declared == set(lifecycle.STATUSES)


def test_one_current_permanent_index_matches_the_code(sql):
    pred = _index_predicate(sql, "tpn_one_current_permanent")
    assert pred == (f"purpose = 'permanent' and status "
                    f"{_in_list(lifecycle.CURRENT_PERMANENT_STATUSES)}")
    assert "'retiring'" not in pred, ("a retiring predecessor must be allowed to "
                                      "coexist with the current permanent number")


def test_one_live_temporary_index_is_stricter_and_matches_the_code(sql):
    pred = _index_predicate(sql, "tpn_one_live_temporary")
    assert pred == (f"purpose = 'temporary_test' and status "
                    f"{_in_list(lifecycle.LIVE_TEMPORARY_STATUSES)}")
    assert "'retiring'" in pred, ("a retiring temporary must still block a second "
                                  "one, or a tenant accumulates rented numbers")


def test_owned_e164_index_matches_the_code_and_permits_reuse(sql):
    pred = _index_predicate(sql, "tpn_owned_e164_key")
    assert pred == f"status {_in_list(lifecycle.OWNED_E164_STATUSES)}"
    assert "'released'" not in pred, "a released number must be re-purchasable"
    assert "'failed'" not in pred, "a failed purchase must not squat an E.164"
    assert "tpn_owned_e164_key on tenant_phone_numbers (e164)" in sql


def test_one_row_per_provider_object(sql):
    m = re.search(r"tpn_provider_object_key on tenant_phone_numbers \(([^)]*)\)", sql)
    assert m and m.group(1) == "provider, provider_account_sid, provider_sid"


def test_a_routable_number_must_declare_its_provider_identity(sql):
    """A live number whose Twilio account owner is unknown cannot be safely
    released, so the state is forbidden outright."""
    m = re.search(r"constraint tpn_live_identity_chk check \( status not in "
                  r"\((.*?)\) or \(provider_sid is not null and "
                  r"provider_account_sid is not null\)\)", sql)
    assert m
    guarded = {v.strip().strip("'") for v in m.group(1).split(",")}
    assert guarded == set(lifecycle.ROUTABLE_STATUSES)


def test_activated_at_source_cannot_be_the_tenant_creation_date(sql):
    """Signing up is not activating a phone line. The backfill writes NULL rather
    than inventing history, and the column makes that auditable."""
    m = re.search(r"constraint tpn_activated_source_chk check \((.*?)\)\)?,", sql)
    assert m
    assert "tenant_created_at" not in m.group(1)
    assert "created_at" not in m.group(1).replace("activated_at", "")
    for src in lifecycle.ACTIVATED_AT_SOURCES:
        assert f"'{src}'" in sql


# ── event ledger identity ──────────────────────────────────────────────────

def test_event_identity_is_fingerprint_and_occurrence_not_status(sql):
    """A bundle can reach the same status twice (rejected -> corrected ->
    pending-review again). Keying on status would destroy the second transition."""
    m = re.search(r"tre_fingerprint_occurrence_key on tenant_regulatory_events "
                  r"\(([^)]*)\)", sql)
    assert m and m.group(1) == "provider, bundle_sid, fingerprint, occurrence"
    assert "unique index if not exists tre_bundle_status_key" not in sql
    for bad in ("(provider, bundle_sid, bundle_status)",
                "(bundle_sid, bundle_status)"):
        assert f"unique index if not exists tre_fingerprint_occurrence_key on " \
               f"tenant_regulatory_events {bad}" not in sql


def test_fingerprint_is_constrained_to_a_sha256_hex_digest(sql):
    assert "constraint tre_fingerprint_chk check (fingerprint ~ '^[0-9a-f]{64}$')" in sql


def test_event_ledger_stores_no_raw_body(sql):
    """provider_webhook_events keeps raw_envelope jsonb. This ledger must not: the
    form carries Email and FailureReason, which can quote submitted identity."""
    events = sql.split("create table if not exists tenant_regulatory_events")[1]
    events = events.split("create table")[0]
    for forbidden in ("raw_envelope", "raw_body", "raw jsonb", "payload jsonb"):
        assert forbidden not in events


def test_signature_outcome_is_recorded_and_not_optional(sql):
    assert "signature_valid boolean not null" in sql


def test_the_square_ledger_is_left_alone(sql):
    """provider_webhook_events is check (provider in ('square')) and its dedup key
    is (provider, provider_event_id), which a Twilio callback cannot satisfy."""
    assert "provider_webhook_events" not in sql


# ── RLS ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", NEW_TABLES)
def test_rls_is_enabled_on_every_new_table(sql, table):
    assert f"alter table {table} enable row level security" in sql


def test_no_policy_is_created(sql):
    """Repository convention, verified: the backend uses the service-role key and
    the frontend's anon client is used only for supabase.auth. With RLS on and no
    policy, anon is denied by default and there is no client read path to grant."""
    assert "create policy" not in sql
    assert "to anon" not in sql
    assert "grant " not in sql


# ── rollback ───────────────────────────────────────────────────────────────

def test_rollback_is_documented_and_commented_out(raw):
    body = _strip_comments(raw).lower()
    assert "rollback" in raw.lower()
    assert "drop table if exists tenant_phone_numbers" not in body
    commented = raw.lower()
    for table in NEW_TABLES:
        assert f"-- drop table if exists {table}" in commented


def test_rollback_never_touches_the_scalar_phone_state(rollback_ddl):
    """The scalar stays a complete description of every tenant's current permanent
    number throughout, so an application rollback needs none of this."""
    assert rollback_ddl.strip(), "no rollback DDL found to inspect"
    assert "twilio_phone_number" not in rollback_ddl
    assert "twilio_subaccount_sid" not in rollback_ddl
    assert "tenant_locations_tenant_id_id_key" in rollback_ddl
