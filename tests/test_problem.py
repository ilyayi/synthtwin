"""Tests for problem.load: canonical keys, known quantities, clear errors."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from synthtwin.lib.design.problem import load, validate
from synthtwin.core.schemas import Problem, Target

EXAMPLES = Path(__file__).parent.parent / "examples"


def test_load_example() -> None:
    problem = load(EXAMPLES / "problem.yaml")
    assert problem.problem_id == "au-np-15nm"
    assert problem.material == "Au"
    assert problem.knobs["ratio_reductant_precursor"] == (1.0, 7.0)
    assert problem.fixed == {"total_volume_ml": 20.0}
    assert problem.targets["size_cv_pct"].max == 10.0


def write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "problem.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


def base_problem() -> Problem:
    return Problem(
        problem_id="t", text="t", material="Au",
        targets={"size_mean_nm": Target(value=10.0)},
        knobs={"temperature_C": (60.0, 100.0)},
    )


def test_validate_accepts_ratio_and_conc_keys(tmp_path: Path) -> None:
    problem = base_problem()
    problem.knobs = {
        "ratio_reductant_precursor": (1.0, 5.0),
        "conc_precursor_mM": (0.1, 1.0),
    }
    validate(problem)


@pytest.mark.parametrize("key", ["ratio_reductant", "temp_C", "conc_precursor", "Ratio_x_y"])
def test_bad_knob_key_rejected(key: str) -> None:
    problem = base_problem()
    problem.knobs = {key: (1.0, 5.0)}
    with pytest.raises(ValueError, match=key.replace("_", ".*")):
        validate(problem)


def test_all_errors_reported_at_once(tmp_path: Path) -> None:
    data = {
        "problem_id": "t", "text": "t", "material": "",
        "targets": {"shize_mean_nm": {"value": 5}},
        "knobs": {"temperature_C": [100, 60]},
        "fixed": {"temperature_C": 80},
    }
    with pytest.raises(ValueError) as excinfo:
        load(write(tmp_path, data))
    msg = str(excinfo.value)
    assert "material is empty" in msg
    assert "shize_mean_nm" in msg
    assert "empty range" in msg
    assert "both a knob and fixed" in msg


def test_empty_range_and_missing_target_value(tmp_path: Path) -> None:
    data = {
        "problem_id": "t", "text": "t", "material": "Au",
        "targets": {"size_mean_nm": {"weight": 1.0}},
        "knobs": {"time_min": [10, 10]},
    }
    with pytest.raises(ValueError, match="no value, min or max"):
        load(write(tmp_path, data))
