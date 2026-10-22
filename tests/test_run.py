"""End-to-end tests for the synthtwin-design CLI on the examples."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent / "stubs"))

from synthtwin.lib.design.run import main  # noqa: E402

EXAMPLES = Path(__file__).parent.parent / "examples"
ARGS = [
    str(EXAMPLES / "problem.yaml"),
    "--library", str(EXAMPLES / "recipes.jsonl"),
    "--robot", str(EXAMPLES / "robot.yaml"),
    "--predictor", "np_stub",
]


def run_cli(tmp_path: Path, extra: list[str] | None = None) -> int:
    out = tmp_path / "out"
    code = main(ARGS + (extra or []) + ["--out", str(out)])
    return code


def test_end_to_end_three_proposals(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert main(ARGS + ["--out", str(out)]) == 0
    data = json.loads((out / "proposals.json").read_text())
    assert data["problem_id"] == "au-np-15nm"
    assert len(data["proposals"]) == 3
    p = data["proposals"][0]
    assert p["steps"] and p["measurements"] and p["controls"] and p["risks"]
    assert p["novelty"]["novel"] is True
    assert p["candidate"]["predicted"]["lspr_nm"]["value"] > 500

    report = (out / "report.md").read_text()
    for section in ["## Problem", "## Known recipes", "## Calibration", "## Candidates",
                    "## Novelty", "## Proposals", "## Assumptions"]:
        assert section in report
    assert "novelty check: synthtwin.lib.recipes.novelty.check" in report   # search/novelty named
    assert "synthetic" in report.lower() # library rows carry their source


def test_deterministic_output(tmp_path: Path) -> None:
    assert run_cli(tmp_path) == 0
    first = (tmp_path / "out" / "proposals.json").read_text()
    assert run_cli(tmp_path, ["--seed", "0"]) == 0
    assert (tmp_path / "out" / "proposals.json").read_text() == first


def test_validated_json_marks_region(tmp_path: Path) -> None:
    validated = tmp_path / "validated.json"
    validated.write_text(json.dumps({
        "citrate reduction": {
            "ratio_reductant_precursor": [1.0, 7.0],
            "temperature_C": [70.0, 100.0],
            "conc_precursor_mM": [0.1, 1.0],
        }
    }))
    assert run_cli(tmp_path, ["--validated", str(validated)]) == 0
    data = json.loads((tmp_path / "out" / "proposals.json").read_text())
    assert all(p["candidate"]["in_validated_region"] for p in data["proposals"])
    assert "yes" in (tmp_path / "out" / "report.md").read_text()


def test_invalid_problem_clear_message_no_proposals(tmp_path: Path, capsys) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({
        "problem_id": "bad", "text": "t", "material": "Au",
        "targets": {"shize_mean_nm": {"value": 5}},
        "knobs": {"temperature_C": [80, 100]},
    }))
    out = tmp_path / "out"
    code = main([str(bad), "--library", str(EXAMPLES / "recipes.jsonl"),
                 "--robot", str(EXAMPLES / "robot.yaml"),
                 "--predictor", "np_stub", "--out", str(out)])
    assert code == 1
    assert "invalid problem" in capsys.readouterr().err
    assert not (out / "proposals.json").exists()
    assert "shize_mean_nm" in (out / "report.md").read_text()


def test_robot_cannot_run_anything_no_proposals(tmp_path: Path, capsys) -> None:
    cold = tmp_path / "cold-robot.yaml"
    cold.write_text(yaml.safe_dump({
        "name": "cold", "operations": ["dispense"], "reagents": ["water"],
        "temperature_C": [20.0, 40.0], "volume_ml": [0.2, 50.0],
        "instruments": ["UV-Vis"], "batch_size": 1,
    }))
    out = tmp_path / "out"
    code = main([
        str(EXAMPLES / "problem.yaml"),
        "--library", str(EXAMPLES / "recipes.jsonl"),
        "--robot", str(cold), "--predictor", "np_stub", "--out", str(out),
    ])
    assert code == 1
    assert "no proposals" in capsys.readouterr().err
    data = json.loads((out / "proposals.json").read_text())
    assert data["proposals"] == []


def cli_args(tmp_path: Path, predictor: str) -> list[str]:
    return [
        str(EXAMPLES / "problem.yaml"),
        "--library", str(EXAMPLES / "recipes.jsonl"),
        "--robot", str(EXAMPLES / "robot.yaml"),
        "--predictor", predictor,
        "--out", str(tmp_path),
    ]


def test_missing_predictor_module(tmp_path: Path, capsys) -> None:
    assert main(cli_args(tmp_path, "no_such_module_xyz")) == 1
    assert "cannot load predictor" in capsys.readouterr().err


def test_predictor_without_calibrate_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "half_mod.py").write_text("def predict(params):\n    return {}\n")
    sys.path.insert(0, str(tmp_path))
    try:
        assert main(cli_args(tmp_path / "o", "half_mod")) == 1
    finally:
        sys.path.remove(str(tmp_path))
