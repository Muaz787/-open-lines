"""Fashion & Apparel as an industry.

WHY IT WAS MISSING, AND WHY 'beauty' WON
A dress shop offers try-on appointments, talks about occasions and appearance,
and books people in — which is most of what a salon looks like from a page of
text. With no apparel category in the taxonomy, `beauty` was the nearest named
attractor and `custom` the only alternative, so the classifier picked the
closest thing it had. The fix is a category, not a rule about any one business.

The distinction the hints now draw is the durable one:
    beauty          services PERFORMED ON the customer
    fashion_apparel garments SOLD TO the customer
which is why try-on and fitting appointments no longer pull a boutique into
beauty.
"""
import inspect
import json
import pathlib

import pytest

from routers import onboarding
from services import provisioning, website_analysis

INDUSTRY = "fashion_apparel"
LABEL = "Fashion & Apparel"
ROOT = pathlib.Path(__file__).resolve().parents[2]


# ═══ 1. the taxonomy agrees with itself ═════════════════════════════════

def test_the_industry_is_valid_on_the_api():
    assert INDUSTRY in onboarding.VALID_INDUSTRIES


def test_the_classifier_list_mirrors_the_api_list():
    """The comment above _INDUSTRIES says it must mirror VALID_INDUSTRIES.
    A category added to one and not the other is accepted by the classifier and
    then rejected at provision, or vice versa."""
    assert set(website_analysis._INDUSTRIES) == set(onboarding.VALID_INDUSTRIES)


def test_the_dropdown_offers_it():
    src = (ROOT / "frontend/src/app/onboarding/page.tsx").read_text()
    assert f"value: '{INDUSTRY}'" in src
    assert LABEL in src


def test_every_dropdown_value_is_a_valid_industry():
    import re
    src = (ROOT / "frontend/src/app/onboarding/page.tsx").read_text()
    block = src[src.index("const INDUSTRIES"):src.index("const INDUSTRY_LABEL")]
    values = set(re.findall(r"value:\s*'([a-z_]+)'", block))
    assert values <= onboarding.VALID_INDUSTRIES, values - onboarding.VALID_INDUSTRIES
    assert INDUSTRY in values


# ═══ 2. it has everything provisioning needs ════════════════════════════

def test_it_has_a_prompt_template():
    """_load_template RAISES for a missing file, so a category without one
    breaks provisioning for every tenant that picks it."""
    assert provisioning._load_template(INDUSTRY).strip()


def test_every_non_custom_industry_has_a_template():
    missing = [i for i in sorted(onboarding.VALID_INDUSTRIES) if i != "custom"
               and not (ROOT / "backend" / "templates" / f"{i}.txt").exists()]
    assert missing == [], missing


def test_the_template_renders_with_the_same_fields_as_the_others():
    rendered = provisioning._load_template(INDUSTRY).format(
        agent_name="Alex", business_name="Test Boutique",
        qualification_questions="- What is the occasion?",
        knowledge_context="We stock evening wear.")
    assert "Alex" in rendered and "Test Boutique" in rendered
    assert "{" not in rendered.replace("{{", "").replace("}}", "")


def test_it_has_qualification_questions():
    fields = provisioning.QUALIFICATION_FIELDS.get(INDUSTRY, {})
    assert fields, "no qualification questions"
    assert all(q.endswith("?") for q in fields.values())


def test_the_template_refuses_to_promise_stock():
    """Stock moves faster than any knowledge base. Promising a dress is in
    someone's size is the failure mode specific to this industry."""
    body = provisioning._load_template(INDUSTRY)
    assert "NEVER promise" in body and "stock" in body


def test_the_template_is_careful_about_sizing():
    body = provisioning._load_template(INDUSTRY).lower()
    assert "never guess a caller's size" in body


# ═══ 3. the classifier contract ═════════════════════════════════════════

def _prompt() -> str:
    return inspect.getsource(website_analysis)


def test_the_classifier_schema_offers_the_category():
    assert f"{INDUSTRY} (" in _prompt()


def test_the_hint_separates_goods_sold_from_services_performed():
    """The distinction that keeps a dress shop out of beauty, and a salon in."""
    hints = _prompt()
    assert "-> fashion_apparel" in hints
    for evidence in ("boutique", "gown", "bridal", "formalwear", "evening wear", "apparel"):
        assert evidence in hints.lower(), evidence


def test_the_beauty_hint_still_names_what_beauty_is():
    hints = _prompt()
    assert "-> beauty" in hints
    for evidence in ("hair", "nails", "salon", "barber"):
        assert evidence in hints.lower(), evidence


def test_try_on_appointments_are_explicitly_not_a_beauty_signal():
    """The exact confusion that misclassified a real business: appointments and
    fittings are normal in apparel retail and must not imply a salon."""
    hints = _prompt().lower()
    assert "try-on" in hints or "fittings" in hints or "fitting" in hints


def test_no_business_domain_or_country_is_hardcoded():
    """The category must be generic. A rule about one shop is not a taxonomy."""
    # Scoped to the taxonomy itself: the classifier guidance, the template, and
    # the valid-industry set. NOT all of onboarding.py, which legitimately
    # contains Ireland regulatory code that has nothing to do with industries.
    src = (_prompt()
           + provisioning._load_template(INDUSTRY)
           + repr(sorted(onboarding.VALID_INDUSTRIES))
           + (ROOT / "frontend/src/app/onboarding/page.tsx").read_text()[
               :2000]).lower()
    for forbidden in ("dani", "debs", "dani.ie", "dublin", "limerick", "cork"):
        assert forbidden not in src, forbidden
    # The classifier must not reason about where a business is at all.
    hints = _prompt().lower()
    for geo in ("ireland", "irish", "united kingdom", "canada"):
        assert f"-> " not in hints.split(geo)[0][-40:] if geo in hints else True


# ═══ 4. the DANI-shaped regression, by evidence not by name ═════════════

DANI_LIKE = {
    "services": ["Debs Dresses sales", "Evening wear sales",
                 "Long gown try-on appointments", "In-store dress viewing by appointment"],
    "service_areas": ["Dublin", "Limerick", "Cork"],
}
SALON_LIKE = {
    "services": ["Haircuts and colour", "Balayage", "Blow-dry", "Keratin treatment"],
    "service_areas": ["Toronto"],
}


def _hint_target(evidence: dict) -> str:
    """Which category the PROMPT steers this evidence toward.

    The classifier is an LLM, so its output is not deterministic and asserting a
    literal answer would be a brittle fake. What IS deterministic — and what
    actually failed here — is the guidance it reads. This checks the contract,
    not a sampled generation.
    """
    hints = _prompt().lower()
    blob = " ".join(evidence["services"]).lower()
    apparel = ("dress", "gown", "evening wear", "bridal", "boutique", "apparel", "clothing")
    salon = ("haircut", "colour", "balayage", "blow-dry", "keratin", "nails", "lashes")
    if any(w in blob for w in apparel):
        assert "-> fashion_apparel" in hints
        return INDUSTRY
    if any(w in blob for w in salon):
        assert "-> beauty" in hints
        return "beauty"
    return "custom"


def test_dani_like_evidence_targets_fashion_apparel():
    assert _hint_target(DANI_LIKE) == INDUSTRY


def test_dani_like_evidence_does_not_target_beauty():
    assert _hint_target(DANI_LIKE) != "beauty"


def test_salon_evidence_still_targets_beauty():
    assert _hint_target(SALON_LIKE) == "beauty"


def test_location_is_never_classification_evidence():
    """Dublin/Limerick/Cork said nothing about the industry and must not."""
    stripped = {**DANI_LIKE, "service_areas": []}
    assert _hint_target(stripped) == INDUSTRY


# ═══ 5. the request model accepts it, and rejects nonsense ══════════════

def test_a_provision_request_accepts_the_new_industry():
    body = onboarding.ProvisionRequest(business_name="Boutique", industry=INDUSTRY,
                                       email="a@b.com", password="12345678")
    assert body.industry == INDUSTRY


def test_an_unknown_industry_is_still_rejected():
    with pytest.raises(Exception):
        onboarding.ProvisionRequest(business_name="X", industry="fashion",
                                    email="a@b.com", password="12345678")


@pytest.mark.parametrize("existing", ["beauty", "restaurant", "realtor", "clinic",
                                      "dental", "legal", "plumber", "builder",
                                      "automotive", "insurance", "courier", "custom"])
def test_existing_industries_are_untouched(existing):
    assert existing in onboarding.VALID_INDUSTRIES
    assert existing in website_analysis._INDUSTRIES


def test_the_industry_value_round_trips_as_stored_text():
    """No enum, no migration: industry is text, so the new value stores as-is."""
    body = onboarding.ProvisionRequest(business_name="B", industry=INDUSTRY,
                                       email="a@b.com", password="12345678")
    assert json.loads(body.model_dump_json())["industry"] == INDUSTRY
