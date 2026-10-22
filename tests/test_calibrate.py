"""Tests for calibrate.family: family selection, merge, spread, uncalibrated."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "stubs"))

import np_stub  # noqa: E402

from synthtwin.lib.design.calibrate import UNCALIBRATED_BAND_FACTOR, family
from synthtwin.core.schemas import Outcome, Problem, Recipe, Reagent, Target

LIBRARY = [
    Recipe.model_validate_json(line)
    for line in (Path(__file__).parent.parent / "examples" / "recipes.jsonl").read_text().splitlines()
    if line.strip()
]

PROBLEM = Problem(
    problem_id="t", text="t", material="Au", methods=["citrate reduction"],
    targets={"size_mean_nm": Target(value=15.0)},
    knobs={"ratio_reductant_precursor": (1.0, 7.0)},
)


def test_family_calibrates_on_matching_recipes() -> None:
    cal = family(np_stub, LIBRARY, PROBLEM)
    assert cal.status == "calibrated"
    assert cal.n == len(LIBRARY) == 12
    assert set(cal.recipe_ids) == {r.recipe_id for r in LIBRARY}
    # library size law is ~7% below the stub's, so the fitted scale sits near 0.93
    assert 0.85 < cal.params["size_scale"] < 1.0
    assert cal.spread is not None and 0 < cal.spread < 0.10
    assert cal.band_factor == pytest.approx(1.0 + cal.spread)


def test_method_filter_excludes_other_families() -> None:
    problem = PROBLEM.model_copy(update={"methods": ["borohydride reduction"]})
    cal = family(np_stub, LIBRARY, problem)
    assert cal.status == "uncalibrated"
    assert cal.n == 0
    assert cal.params == {}
    assert cal.band_factor == UNCALIBRATED_BAND_FACTOR
    assert any("no library recipes" in note for note in cal.notes)


def test_recipes_without_outcomes_or_conditions_are_skipped() -> None:
    bare = Recipe(
        recipe_id="x:1", source="manual", material="Au", method="citrate reduction",
        conditions={"temperature_C": 90.0},
        outcomes=[Outcome(quantity="size_mean_nm", value=20.0, unit="nm")],
    )
    measured_but_thin = Recipe(
        recipe_id="x:2", source="manual", material="Au", method="citrate reduction",
        conditions={"temperature_C": 90.0, "ratio_reductant_precursor": 3.0},
        outcomes=[Outcome(quantity="size_mean_nm", value=20.0, unit="nm")],
    )
    cal = family(np_stub, [bare, measured_but_thin], PROBLEM)
    assert cal.n == 1
    assert cal.recipe_ids == ["x:2"]


def test_predictor_failure_on_one_recipe_does_not_kill_calibration() -> None:
    class Flaky:
        calls = 0

        @staticmethod
        def calibrate(params, outcomes):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise RuntimeError("cannot calibrate this one")
            return np_stub.calibrate(params, outcomes)

        @staticmethod
        def predict(params):
            return np_stub.predict(params)

    cal = family(Flaky, LIBRARY[:2], PROBLEM)
    assert cal.status == "calibrated"
    assert cal.n == 2  # n counts family recipes, not successful calibrations
    assert "size_scale" in cal.params


def test_empty_methods_means_any_library_method() -> None:
    problem = PROBLEM.model_copy(update={"methods": []})
    cal = family(np_stub, LIBRARY, problem)
    assert cal.status == "calibrated"
    assert cal.n == 12
