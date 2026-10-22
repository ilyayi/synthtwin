"""Search: material/method filtering, target-outcome coverage, knob and
outcome closeness, one-line reasons."""
from __future__ import annotations

import pytest

from synthtwin.lib.recipes.search import knob_closeness, search, target_closeness
from synthtwin.core.schemas import Outcome, Problem, Recipe, Target


def recipe(id, material="Au", method="citrate reduction", conditions=None,
           outcomes=(), extraction=None):
    return Recipe(
        recipe_id=id, source="lematsynth", material=material, method=method,
        conditions=conditions or {}, outcomes=list(outcomes),
        extraction_score=extraction,
    )


@pytest.fixture
def library():
    return [
        recipe("a", conditions={"temperature_C": 90.0},
               outcomes=[Outcome(quantity="size_mean_nm", value=15.0, unit="nm")]),
        recipe("b", conditions={"temperature_C": 90.0, "ratio_reductant_precursor": 3.5},
               outcomes=[Outcome(quantity="size_mean_nm", value=9.0, unit="nm"),
                         Outcome(quantity="size_sd_nm", value=0.8, unit="nm")]),
        recipe("c", method="borohydride reduction",
               outcomes=[Outcome(quantity="size_mean_nm", value=5.0, unit="nm")]),
        recipe("d", material="Ag",
               outcomes=[Outcome(quantity="size_mean_nm", value=20.0, unit="nm")]),
        recipe("e", conditions={"temperature_C": 250.0}),  # no outcomes
    ]


@pytest.fixture
def problem():
    return Problem(
        problem_id="p", text="8 nm Au", material="Au",
        methods=["citrate reduction"],
        targets={"size_mean_nm": Target(value=8.0),
                 "size_sd_nm": Target(max=1.5)},
        knobs={"ratio_reductant_precursor": (1.0, 10.0),
               "temperature_C": (20.0, 110.0)},
    )


def test_filters_material_and_methods(library, problem):
    hits = search(problem, library)
    ids = [r.recipe_id for r, _, _ in hits]
    assert ids == ["b", "a", "e"]  # Ag and borohydride rows filtered out
    problem_any = problem.model_copy(update={"methods": []})
    ids = [r.recipe_id for r, _, _ in search(problem_any, library)]
    assert set(ids) == {"a", "b", "c", "e"}


def test_ranking_prefers_target_coverage_and_closeness(library, problem):
    hits = search(problem, library)
    top_recipe, top_score, reason = hits[0]
    assert top_recipe.recipe_id == "b"  # has both targets, size near 8, knobs in bounds
    assert top_score > hits[1][1]
    assert "size_mean_nm 9 vs 8" in reason
    assert "ratio_reductant_precursor 3.5 in [1, 10]" in reason


def test_knobs_outside_bounds_score_lower():
    problem = Problem(
        problem_id="p2", text="", material="Au", targets={},
        knobs={"temperature_C": (20.0, 100.0)})
    inside = recipe("in", conditions={"temperature_C": 60.0})
    edge = recipe("edge", conditions={"temperature_C": 150.0})
    far = recipe("far", conditions={"temperature_C": 400.0})
    assert knob_closeness(problem, inside) == (1.0, ["temperature_C 60 in [20, 100]"])
    assert knob_closeness(problem, edge)[0] == pytest.approx(0.375)  # 50 above / 80 span
    assert knob_closeness(problem, far)[0] == 0.0
    assert knob_closeness(problem, recipe("none"))[0] == 0.0


def test_target_closeness():
    t = Target(value=8.0)
    assert target_closeness(t, 8.0) == 1.0
    assert target_closeness(t, 12.0) == pytest.approx(0.5)
    assert target_closeness(t, 16.0) == 0.0
    t = Target(min=5.0, max=10.0)
    assert target_closeness(t, 7.0) == 1.0
    assert target_closeness(t, 15.0) == 0.0
    t = Target(max=1.5)
    assert target_closeness(t, 1.0) == 1.0


def test_k_limits_results(library, problem):
    assert len(search(problem, library, k=1)) == 1
