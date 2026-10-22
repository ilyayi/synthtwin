"""Novelty edge cases: same-family filtering, tolerance distances, thin
coverage, condition-less recipes, tolerance overrides."""
from __future__ import annotations

import pytest

from synthtwin.lib.recipes.novelty import check, tolerance_for
from synthtwin.core.schemas import Recipe, Reagent


def recipe(id, material="Au", method="citrate reduction", conditions=None,
           reagents=()):
    return Recipe(
        recipe_id=id, source="lematsynth", material=material, method=method,
        conditions=conditions or {}, reagents=list(reagents),
    )


CITRATE = [Reagent(role="reductant", name="trisodium citrate")]
BH4 = [Reagent(role="reductant", name="sodium borohydride")]


@pytest.fixture
def library():
    base = {"temperature_C": 90.0, "ratio_reductant_precursor": 3.5,
            "conc_precursor_mM": 0.5}
    return [
        recipe("near", conditions=base, reagents=CITRATE),
        recipe("near2", conditions={**base, "temperature_C": 92.0}, reagents=CITRATE),
        recipe("far", conditions={**base, "ratio_reductant_precursor": 20.0},
               reagents=CITRATE),
        recipe("other-material", material="Ag", conditions=base, reagents=CITRATE),
        recipe("other-method", method="borohydride reduction", conditions=base,
               reagents=CITRATE),
    ]


def test_identical_recipe_is_not_novel(library):
    cand = {"material": "Au", "method": "citrate reduction", "reagents": CITRATE,
            "conditions": {"temperature_C": 90.0, "ratio_reductant_precursor": 3.5}}
    verdict = check(cand, library)
    assert verdict.novel is False
    assert verdict.coverage == "ok"
    assert verdict.nearest_recipe_id == "near"
    assert verdict.distance == pytest.approx(0.0)
    assert "matches" in verdict.reason


def test_far_enough_is_novel(library):
    cand = {"material": "Au", "method": "citrate reduction", "reagents": CITRATE,
            "conditions": {"temperature_C": 90.0, "ratio_reductant_precursor": 10.0}}
    verdict = check(cand, library)
    assert verdict.novel is True
    # nearest is 'far' (ratio 20 vs 10: 10/(0.2*20) = 2.5), not 'near'
    # (ratio 3.5 vs 10: 6.5/(0.2*10) = 3.25)
    assert verdict.nearest_recipe_id == "far"
    assert verdict.distance == pytest.approx(2.5)


def test_distance_exactly_one_is_novel(library):
    # temperature tolerance is 5 C: 97 vs 92 (near2) is exactly distance 1
    cand = {"material": "Au", "method": "citrate reduction", "reagents": CITRATE,
            "conditions": {"temperature_C": 97.0, "ratio_reductant_precursor": 3.5,
                           "conc_precursor_mM": 0.5}}
    verdict = check(cand, library)
    assert verdict.novel is True
    assert verdict.distance == pytest.approx(1.0)


def test_different_reductant_is_not_the_family():
    lib = [recipe("cit1", reagents=CITRATE), recipe("cit2", reagents=CITRATE),
           recipe("bh4", reagents=BH4)]
    cand = {"material": "Au", "method": "citrate reduction", "reagents": BH4,
            "conditions": {"temperature_C": 90.0}}
    verdict = check(cand, lib)
    # cit1/cit2 state a different reductant, bh4 a different method: empty pool
    assert verdict.coverage == "thin"
    assert verdict.novel is False


def test_thin_coverage_never_novel():
    lib = [recipe("only", conditions={"temperature_C": 90.0})]
    verdict = check({"material": "Au", "method": "citrate reduction",
                     "conditions": {"temperature_C": 200.0}}, lib)
    assert verdict.novel is False
    assert verdict.coverage == "thin"
    assert "thin" in verdict.reason


def test_unknown_method_still_comparable(library):
    cand = {"material": "Au", "method": "",  # candidate states no method
            "conditions": {"temperature_C": 90.0}}
    verdict = check(cand, library)
    assert verdict.coverage == "ok"
    assert verdict.novel is False  # matches near on temperature


def test_conditionless_library_recipe_does_not_outrank():
    # a recipe sharing a knob always beats one recording nothing, even though
    # the conditionless one is 'distance 0'
    lib = [
        recipe("blank", conditions={}),
        recipe("shares", conditions={"temperature_C": 90.0}),
        recipe("blank2", conditions={}),
    ]
    cand = {"material": "Au", "method": "citrate reduction",
            "conditions": {"temperature_C": 93.0}}
    verdict = check(cand, lib)
    assert verdict.nearest_recipe_id == "shares"


def test_all_conditionless_recipes_give_distance_zero():
    lib = [recipe("blank", conditions={}), recipe("blank2", conditions={}),
           recipe("blank3", conditions={})]
    verdict = check({"material": "Au", "method": "citrate reduction",
                     "conditions": {"temperature_C": 93.0}}, lib)
    assert verdict.novel is False
    assert verdict.distance == 0.0
    assert "no shared conditions" in verdict.reason


def test_tolerance_override():
    lib = [
        recipe("r1", conditions={"temperature_C": 90.0}),
        recipe("r2", conditions={"temperature_C": 90.0}),
        recipe("r3", conditions={"temperature_C": 90.0}),
    ]
    cand = {"material": "Au", "method": "citrate reduction",
            "conditions": {"temperature_C": 110.0}}
    tight = check(cand, lib)  # 20 C off / 5 C tol -> distance 4
    loose = check(cand, lib, tol={"temperature_C": ("abs", 50.0)})
    assert tight.novel is True
    assert tight.distance == pytest.approx(4.0)
    assert loose.novel is False
    assert loose.distance == pytest.approx(0.4)


def test_tolerance_for_keys():
    assert tolerance_for("ratio_reductant_precursor") == ("rel", 0.2)
    assert tolerance_for("conc_capping_mM") == ("rel", 0.2)
    assert tolerance_for("temperature_C") == ("abs", 5.0)
    assert tolerance_for("pH") == ("abs", 0.5)
    assert tolerance_for("time_min") == ("rel", 0.5)
    assert tolerance_for("stirring_rpm") == ("rel", 0.5)
    assert tolerance_for("something_new") == ("rel", 0.5)
    assert tolerance_for("temperature_C", {"temperature_C": ("abs", 50.0)}) == ("abs", 50.0)


def test_accepts_recipe_instance(library):
    cand = recipe("cand", conditions={"temperature_C": 90.0}, reagents=CITRATE)
    assert check(cand, library).novel is False


def test_empty_library_is_thin():
    verdict = check({"material": "Au", "method": "citrate reduction"}, [])
    assert verdict.novel is False
    assert verdict.coverage == "thin"
    assert verdict.distance is None
