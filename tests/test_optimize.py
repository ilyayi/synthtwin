"""Tests for optimize.run: objective, diversity, determinism, validated region."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "stubs"))

import np_stub  # noqa: E402

from synthtwin.lib.design.calibrate import family
from synthtwin.lib.design.optimize import run
from synthtwin.core.schemas import Problem, Recipe, Target

LIBRARY = [
    Recipe.model_validate_json(line)
    for line in (Path(__file__).parent.parent / "examples" / "recipes.jsonl").read_text().splitlines()
    if line.strip()
]

PROBLEM = Problem(
    problem_id="t", text="t", material="Au", methods=["citrate reduction"],
    targets={"size_mean_nm": Target(value=15.0), "size_cv_pct": Target(max=10.0, weight=0.5)},
    knobs={
        "ratio_reductant_precursor": (1.0, 7.0),
        "temperature_C": (70.0, 100.0),
        "conc_precursor_mM": (0.1, 1.0),
    },
    fixed={"total_volume_ml": 20.0},
    n_proposals=3,
)

CAL = family(np_stub, LIBRARY, PROBLEM)
VALIDATED = {
    "citrate reduction": {
        "ratio_reductant_precursor": [1.0, 7.0],
        "temperature_C": [70.0, 100.0],
        "conc_precursor_mM": [0.1, 1.0],
    }
}


def test_best_candidate_hits_the_target() -> None:
    cands = run(PROBLEM, np_stub, CAL, validated=VALIDATED)
    assert cands, "expected candidates"
    best = cands[0]
    size = best.predicted["size_mean_nm"]
    assert size.low - 1.0 <= 15.0 <= size.high + 1.0 or abs(size.value - 15.0) < 2.0
    assert best.score <= cands[-1].score
    # cv target is met in value (band may poke past, which the penalty accounts for)
    assert best.predicted["size_cv_pct"].value <= 10.0


def test_returns_diverse_top_candidates() -> None:
    cands = run(PROBLEM, np_stub, CAL, validated=VALIDATED)
    assert len(cands) == 3 * PROBLEM.n_proposals
    lo = {k: v[0] for k, v in PROBLEM.knobs.items()}
    hi = {k: v[1] for k, v in PROBLEM.knobs.items()}
    for i, a in enumerate(cands):
        for b in cands[i + 1:]:
            d = max(
                abs(a.conditions[k] - b.conditions[k]) / (hi[k] - lo[k])
                for k in PROBLEM.knobs
            )
            assert d > 0.02  # at least one knob moves between any two candidates


def test_deterministic_per_seed() -> None:
    a = run(PROBLEM, np_stub, CAL, seed=3, validated=VALIDATED)
    b = run(PROBLEM, np_stub, CAL, seed=3, validated=VALIDATED)
    assert [c.conditions for c in a] == [c.conditions for c in b]
    assert [c.score for c in a] == [c.score for c in b]


def test_different_seed_different_points() -> None:
    a = run(PROBLEM, np_stub, CAL, seed=1, validated=VALIDATED)
    b = run(PROBLEM, np_stub, CAL, seed=2, validated=VALIDATED)
    assert [c.conditions for c in a] != [c.conditions for c in b]


def test_validated_region_flags() -> None:
    tight = {"citrate reduction": {
        "ratio_reductant_precursor": [1.0, 2.0],
        "temperature_C": [70.0, 80.0],
        "conc_precursor_mM": [0.1, 0.2],
    }}
    inside = run(PROBLEM, np_stub, CAL, validated=VALIDATED)
    assert all(c.in_validated_region for c in inside)
    outside = run(PROBLEM, np_stub, CAL, validated=tight)
    assert all(not c.in_validated_region for c in outside)
    assert any("outside the validated range" in n for c in outside for n in c.notes)
    none = run(PROBLEM, np_stub, CAL, validated=None)
    assert all(not c.in_validated_region for c in none)
    assert all("exploratory" in c.notes[0] for c in none)


def test_simulator_failures_are_skipped_not_fatal() -> None:
    class Picky:
        @staticmethod
        def predict(params):
            if params["conditions"]["temperature_C"] > 95.0:
                raise RuntimeError("outside the stub's fit")
            return np_stub.predict(params)

    cands = run(PROBLEM, Picky, CAL, validated=VALIDATED)
    assert cands
    assert all(c.conditions["temperature_C"] <= 95.0 for c in cands)


def test_uncalibrated_still_runs_with_wider_bands() -> None:
    from synthtwin.lib.design.calibrate import Calibration

    cal = Calibration()  # uncalibrated defaults
    cands = run(PROBLEM, np_stub, cal, validated=VALIDATED)
    raw = np_stub.predict({
        "material": "Au", "method": "citrate reduction",
        "conditions": cands[0].conditions, "reagents": [],
    })
    half = (raw["size_mean_nm"]["high"] - raw["size_mean_nm"]["low"]) / 2 * cal.band_factor
    assert cands[0].predicted["size_mean_nm"].high - cands[0].predicted["size_mean_nm"].low \
        == pytest.approx(2 * half, rel=1e-9)


def test_candidates_carry_6040_labels() -> None:
    cands = run(PROBLEM, np_stub, CAL, validated=VALIDATED)
    labels = [c.label for c in cands]
    assert labels.count("exploit") == 5 and labels.count("explore") == 4   # 9 x 0.6 = 5.4 -> 5
    assert cands[0].label == "exploit"                 # the best score is always exploited
    assert all(c.label == "exploit" for c in run(PROBLEM, np_stub, CAL, validated=VALIDATED, explore=0.0))
    assert all(c.label == "explore" for c in run(PROBLEM, np_stub, CAL, validated=VALIDATED, explore=1.0))
