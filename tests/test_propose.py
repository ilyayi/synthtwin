"""Tests for propose.make: robot steps, feasibility, novelty gate, controls."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent / "stubs"))

import np_stub  # noqa: E402

from synthtwin.lib.design.calibrate import family
from synthtwin.lib.design.optimize import run
from synthtwin.lib.design.propose import (
    exact_match_novelty, feasibility, make, parse_stocks,
)
from synthtwin.core.schemas import Candidate, Problem, Recipe, RobotProfile

EXAMPLES = Path(__file__).parent.parent / "examples"
LIBRARY = [
    Recipe.model_validate_json(line)
    for line in (EXAMPLES / "recipes.jsonl").read_text().splitlines() if line.strip()
]
ROBOT = RobotProfile(**yaml.safe_load((EXAMPLES / "robot.yaml").read_text()))
PROBLEM = Problem(
    problem_id="t", text="t", material="Au", methods=["citrate reduction"],
    targets={"size_mean_nm": {"value": 15.0}},
    knobs={
        "ratio_reductant_precursor": (1.0, 7.0),
        "temperature_C": (70.0, 100.0),
        "conc_precursor_mM": (0.1, 1.0),
    },
    fixed={"total_volume_ml": 20.0, "time_min": 30.0},
    n_proposals=3,
)


def candidates() -> list[Candidate]:
    cal = family(np_stub, LIBRARY, PROBLEM)
    return run(PROBLEM, np_stub, cal, validated=None)


def test_parse_stocks() -> None:
    stocks = parse_stocks(ROBOT)
    assert ("HAuCl4", 25.0) in stocks["precursor"]
    assert ("trisodium citrate", 100.0) in stocks["reductant"]
    assert ("water", None) in stocks["solvent"]


def test_make_writes_robot_steps() -> None:
    proposals = make(PROBLEM, candidates(), exact_match_novelty, ROBOT, LIBRARY)
    assert 1 <= len(proposals) <= 3
    p = proposals[0]
    assert p.proposal_id.startswith("t-p")
    total = p.candidate.conditions["total_volume_ml"]
    dispensed = 0.0
    for step in p.steps:
        if step.startswith("Dispense") and "to make up" not in step:
            # "Dispense X.XX mL of <stock> (...)" -> X.XX
            dispensed += float(step.split()[1])
    assert dispensed < total  # solutes leave room for solvent make-up
    assert any("Heat to" in s for s in p.steps)
    assert any("mL/min" in s for s in p.steps)
    assert any("Age at" in s for s in p.steps)
    assert "UV-Vis 300-900 nm" in " ".join(p.measurements)
    assert any("DLS" in m for m in p.measurements)
    assert "lspr_nm" in p.expected and "dls_z_nm" in p.expected


def test_controls_reference_best_match_and_repeat() -> None:
    proposals = make(PROBLEM, candidates(), exact_match_novelty, ROBOT, LIBRARY)
    assert any("control: best-matching known recipe" in c for c in proposals[0].controls)
    assert any("repeat:" in c for c in proposals[0].controls)


def test_exact_recipe_is_rejected_as_not_novel() -> None:
    known = LIBRARY[0]
    cand = Candidate(
        method="citrate reduction", conditions=dict(known.conditions),
        predicted={}, score=0.0, in_validated_region=False,
    )
    nov = exact_match_novelty(cand, LIBRARY)
    assert not nov.novel
    assert nov.nearest_recipe_id == known.recipe_id
    assert make(PROBLEM, [cand], exact_match_novelty, ROBOT, LIBRARY) == []


def test_infeasible_temperature_and_volume_are_dropped() -> None:
    cands = candidates()
    hot = cands[0].model_copy(deep=True)
    hot.conditions["temperature_C"] = 150.0
    huge = cands[0].model_copy(deep=True)
    huge.conditions["total_volume_ml"] = 500.0
    out = make(PROBLEM, [hot, huge], exact_match_novelty, ROBOT, LIBRARY)
    assert out == []


def test_too_dilute_stock_is_infeasible() -> None:
    weak = ROBOT.model_copy(deep=True)
    weak.reagents = ["HAuCl4 0.2 mM (precursor)", "trisodium citrate 0.3 mM (reductant)", "water"]
    stocks = parse_stocks(weak)
    names = {"precursor": "HAuCl4", "reductant": "trisodium citrate"}
    cand = candidates()[0]
    feas = feasibility(cand, weak, stocks, names)
    assert not feas.ok
    assert any("cannot reach the target concentration" in r for r in feas.reasons)


def test_missing_stock_role_is_infeasible() -> None:
    no_reductant = ROBOT.model_copy(deep=True)
    no_reductant.reagents = ["HAuCl4 25.0 mM (precursor)", "water"]
    feas = feasibility(candidates()[0], no_reductant, parse_stocks(no_reductant),
                       {"precursor": "HAuCl4", "reductant": "trisodium citrate"})
    assert not feas.ok


def test_risks_mention_exploratory_and_defaults() -> None:
    proposals = make(PROBLEM, candidates(), exact_match_novelty, ROBOT, LIBRARY)
    risks = proposals[0].risks
    assert any("exploratory" in r for r in risks)
    assert any("assumed" in r for r in risks)
