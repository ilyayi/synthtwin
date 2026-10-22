"""Sweep CLI end-to-end: build from gold fixtures, null and stub-model
baselines, score to sweep_scores.jsonl + markdown table."""
from __future__ import annotations

import json

import pytest

from synthtwin.core.schemas import SweepCase, SweepPrediction, SweepScore
from synthtwin import cli

from conftest import SWEEP_GOLD_DIR

CASE_IDS = ["np-ag-seed-c", "np-au-citrate-a", "np-au-ph-b"]


def build(tmp_path):
    cards, vault = tmp_path / "cards", tmp_path / "vault"
    assert cli.main(["sweep", "build", str(SWEEP_GOLD_DIR), str(cards), str(vault)]) == 0
    return cards, vault


def test_build_writes_cards_and_vault(tmp_path):
    cards, vault = build(tmp_path)
    assert sorted(p.stem for p in cards.glob("*.json")) == CASE_IDS
    for cid in CASE_IDS:
        assert (vault / f"{cid}.json").stat().st_mode & 0o777 == 0o600
    card = SweepCase.model_validate_json((cards / "np-au-citrate-a.json").read_text())
    assert card.anchor_label == "r5"
    assert {o.value for o in card.anchor_outcomes} == {18.0, 19.0}


def test_build_canary_stable_across_rebuilds(tmp_path):
    cards, vault = build(tmp_path)
    before = {
        cid: json.loads((vault / f"{cid}.json").read_text())["canary"] for cid in CASE_IDS
    }
    cli.main(["sweep", "build", str(SWEEP_GOLD_DIR), str(cards), str(vault)])
    after = {
        cid: json.loads((vault / f"{cid}.json").read_text())["canary"] for cid in CASE_IDS
    }
    assert before == after and all(before.values())


def test_null_baseline_then_score(tmp_path, capsys):
    cards, vault = build(tmp_path)
    pred_path = tmp_path / "sweep_predictions.jsonl"
    assert cli.main(["sweep", "baseline", str(cards), "--predictor", "null",
                     "-o", str(pred_path)]) == 0
    preds = [SweepPrediction.model_validate_json(l) for l in pred_path.read_text().splitlines()]
    assert [p.case_id for p in preds] == CASE_IDS
    assert all(p.predictor == "null" for p in preds)

    assert cli.main(["sweep", "score", str(cards), str(vault), str(pred_path)]) == 0
    out = tmp_path / "sweep_scores.jsonl"
    scores = [SweepScore.model_validate_json(l) for l in out.read_text().splitlines()]
    assert len(scores) == 6  # 3 cases x 2 quantities
    a_size = next(s for s in scores
                  if s.case_id == "np-au-citrate-a" and s.quantity == "size_mean_nm")
    assert a_size.predictor == "null"
    assert a_size.spearman is None and not a_size.trend_ok
    assert a_size.mae == pytest.approx(12.25)
    assert a_size.band_coverage == pytest.approx(0.0)

    table = (tmp_path / "sweep_scores.md").read_text()
    assert "np-au-citrate-a" in table and "size_mean_nm" in table
    printed = capsys.readouterr().out
    assert "size_cv_pct" in printed  # the table is printed too


def test_model_baseline_with_stub(tmp_path):
    cards, vault = build(tmp_path)
    pred_path = tmp_path / "model_predictions.jsonl"
    rc = cli.main(["sweep", "baseline", str(cards), "--predictor", "model",
                   "--model", "stub_np_model:make_model", "-o", str(pred_path)])
    assert rc == 0
    preds = [SweepPrediction.model_validate_json(l) for l in pred_path.read_text().splitlines()]
    assert [p.case_id for p in preds] == CASE_IDS
    assert all(p.predictor == "baseline" for p in preds)

    assert cli.main(["sweep", "score", str(cards), str(vault), str(pred_path)]) == 0
    scores = [SweepScore.model_validate_json(l)
              for l in (tmp_path / "sweep_scores.jsonl").read_text().splitlines()]
    a_size = next(s for s in scores
                  if s.case_id == "np-au-citrate-a" and s.quantity == "size_mean_nm")
    assert a_size.trend_ok and a_size.spearman == pytest.approx(1.0)


def test_model_predictor_needs_model(tmp_path, capsys):
    cards, _ = build(tmp_path)
    rc = cli.main(["sweep", "baseline", str(cards), "--predictor", "model",
                   "-o", str(tmp_path / "p.jsonl")])
    assert rc == 1
    assert "predict/calibrate" in capsys.readouterr().err
