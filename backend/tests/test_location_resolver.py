"""
W4 — turning what a caller said into one of the tenant's locations.

The bar here is deliberately higher than for service or staff matching. A wrong
service is read back and corrected in the next sentence; a wrong city is not
noticed until someone drives to it. So: no fallback, a high fuzzy threshold, a
required gap to the runner-up, and clarification whenever those aren't met.
"""
import pytest

from services import location_resolver as lr
from services import location_normalization as norm


def _loc(slug, name, aliases=None, lid=None):
    return {"id": lid or f"loc-{slug}", "slug": slug, "name": name,
            "aliases": aliases or []}


CORK = _loc("cork", "Cork", ["dani cork", "cork showroom"])
DUBLIN = _loc("dublin", "Dublin", ["dani dublin"])
LIMERICK = _loc("limerick", "Limerick")
DANI = [CORK, DUBLIN, LIMERICK]


def _r(spoken, locations=None, business="DANI"):
    return lr.resolve(spoken, locations if locations is not None else DANI,
                      business_name=business)


# ── the happy ladder ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("spoken", [
    "cork", "Cork", "CORK", " cork ", "Cork.", "Cork!",
    "Dani Cork", "dani cork", "the Cork shop", "Cork branch",
    "your Cork showroom", "the cork location", "Cork please",
])
def test_all_the_ways_a_caller_says_cork(spoken):
    res = _r(spoken)
    assert res.ok, f"{spoken!r} -> {res.status} ({res.reason})"
    assert res.location["slug"] == "cork"


def test_exact_slug_wins_first():
    assert _r("cork").reason == "slug"


def test_alias_resolves():
    res = _r("cork showroom")
    assert res.ok and res.location["slug"] == "cork"


def test_normalized_name_resolves():
    res = lr.resolve("Limerick", DANI, business_name="DANI")
    assert res.ok and res.location["slug"] == "limerick"


def test_containment_resolves_uniquely():
    res = _r("somewhere near dublin")
    assert res.ok and res.location["slug"] == "dublin"


def test_fuzzy_accepts_a_clear_winner():
    res = _r("corke")                       # one-letter typo, no rival
    assert res.ok and res.location["slug"] == "cork"


# ── refusals ─────────────────────────────────────────────────────────────────

def test_unknown_location_is_unresolved_with_candidates():
    res = _r("Galway")
    assert res.status == lr.UNRESOLVED
    assert sorted(res.candidate_names()) == ["Cork", "Dublin", "Limerick"]


def test_pure_noise_does_not_resolve():
    """'the shop' names no city. Picking one would be a guess."""
    res = _r("the shop please")
    assert not res.ok
    assert res.status == lr.UNRESOLVED


def test_empty_input_does_not_resolve():
    assert _r("").status == lr.UNRESOLVED
    assert _r("   ").status == lr.UNRESOLVED


def test_ambiguous_between_two_similar_names_refuses():
    locs = [_loc("cork-city", "Cork City"), _loc("cork-retail", "Cork Retail Park")]
    res = lr.resolve("Cork", locs, business_name="DANI")
    assert res.status == lr.AMBIGUOUS
    assert len(res.candidates) == 2


def test_fuzzy_refuses_when_two_candidates_are_equally_close():
    locs = [_loc("marina", "Marino"), _loc("marino", "Marina")]
    res = lr.resolve("Marinø", locs, business_name="")
    assert res.status in (lr.AMBIGUOUS, lr.UNRESOLVED)
    assert not res.ok


def test_no_candidates_when_tenant_has_no_eligible_locations():
    assert lr.resolve("Cork", [], business_name="DANI").status == lr.NO_CANDIDATES


def test_resolution_never_invents_a_location():
    """Across a spread of junk inputs, nothing is ever resolved."""
    for junk in ("asdfgh", "12345", "the thing", "??", "location"):
        assert not _r(junk).ok, junk


# ── security ─────────────────────────────────────────────────────────────────

def test_a_square_provider_id_is_refused_even_though_it_is_a_real_id():
    """The model must never be able to hand us a provider id and have it treated
    as authoritative — that would bypass human-readable resolution entirely."""
    res = lr.resolve("L0Q8GTAZCHD42", DANI, business_name="DANI",
                     provider_ids={"L0Q8GTAZCHD42"})
    assert res.status == lr.UNRESOLVED
    assert "provider identifier" in res.reason


def test_anything_shaped_like_a_provider_id_is_refused_even_if_unknown():
    res = lr.resolve("L9SA1AQ7XBM6K", DANI, business_name="DANI")
    assert not res.ok


def test_provider_id_cannot_sneak_in_as_an_alias_match():
    sneaky = [{**CORK, "aliases": ["L0Q8GTAZCHD42"]}]
    res = lr.resolve("L0Q8GTAZCHD42", sneaky, business_name="DANI")
    assert not res.ok


def test_resolver_only_sees_the_locations_it_is_given():
    """Tenant isolation is structural: it cannot reach a row that was not passed."""
    res = lr.resolve("Dublin", [CORK], business_name="DANI")
    assert not res.ok


# ── clarification text ───────────────────────────────────────────────────────

def test_clarification_lists_names_never_ids():
    text = lr.clarification_text(DANI)
    assert "Cork, Dublin or Limerick" in text
    for l in DANI:
        assert l["id"] not in text
    assert "L0Q8" not in text


def test_clarification_handles_one_and_two_candidates():
    assert "Cork?" in lr.clarification_text([CORK])
    assert "Cork or Dublin?" in lr.clarification_text([CORK, DUBLIN])


# ── shared normalization ─────────────────────────────────────────────────────

def test_adoption_and_resolution_agree_on_what_dani_cork_means():
    """The reason normalization was extracted: a location adopted under one
    spelling must be reachable under the same one."""
    from services import location_adoption
    assert location_adoption.derive_slug("Dani Cork", "DANI") == "cork"
    assert norm.normalize("the Cork shop", "DANI") == "cork"
    assert norm.normalize("Dani Cork", "DANI") == "cork"


def test_normalizer_is_pure():
    """No I/O and no provider concepts in the executable code.

    Checks the module's imports and function bodies via AST rather than raw text:
    the docstring legitimately explains why Square names are normalised, and an
    earlier version of this test failed on its own prose.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(norm))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"re", "__future__"}, f"normalization imported {imported}"

    assert not [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)], \
        "normalization must have no async surface"

    code = "\n".join(
        ast.unparse(n) for n in tree.body if not isinstance(n, ast.Expr))
    assert "square" not in code.lower(), "no provider concepts in normalization code"
