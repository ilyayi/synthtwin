"""CLI end-to-end: build from gold fixtures, null baseline, score to
scores.jsonl + markdown table. The model-dependent 'baseline' predictor
only gets its error path tested here (test_baseline.py covers it with a stub)."""
from __future__ import annotations

import json

import pytest

from synthtwin.schemas import CaseCard, CasePrediction, CaseScore
from synthtwin import cli

from conftest import GOLD_DIR

CASE_IDS = ["co-pd-particle-b", "co-pt-dispersion-c", "co-pt-loading-a"]


def build(tmp_path):
    cards, vault = tmp_path / "cards", tmp_path / "vault"
    assert cli.main(["build", str(GOLD_DIR), str(cards), str(vault)]) == 0
    return cards, vault


def test_build_writes_cards_and_vault(tmp_path):
    cards, vault = build(tmp_path)
    assert sorted(p.stem for p in cards.glob("*.json")) == CASE_IDS
    for cid in CASE_IDS:
        assert (vault / f"{cid}.json").stat().st_mode & 0o777 == 0o600
    card = CaseCard.model_validate_json((cards / "co-pt-loading-a.json").read_text())
    assert card.anchor_label == "1.0Pt" and card.anchor_t50_K == 440.0


def test_build_canary_stable_across_rebuilds(tmp_path):
    cards, vault = build(tmp_path)
    before = {
        cid: json.loads((vault / f"{cid}.json").read_text())["canary"] for cid in CASE_IDS
    }
    cli.main(["build", str(GOLD_DIR), str(cards), str(vault)])
    after = {
        cid: json.loads((vault / f"{cid}.json").read_text())["canary"] for cid in CASE_IDS
    }
    assert before == after and all(before.values())


def test_baseline_null_then_score(tmp_path, capsys):
    cards, vault = build(tmp_path)
    pred_path = tmp_path / "predictions.jsonl"
    assert cli.main(["baseline", str(cards), "--predictor", "null", "-o", str(pred_path)]) == 0
    preds = [CasePrediction.model_validate_json(l) for l in pred_path.read_text().splitlines()]
    assert [p.case_id for p in preds] == CASE_IDS
    assert all(p.predictor == "null" for p in preds)

    assert cli.main(["score", str(cards), str(vault), str(pred_path)]) == 0
    out = tmp_path / "scores.jsonl"
    scores = [CaseScore.model_validate_json(l) for l in out.read_text().splitlines()]
    by_case = {s.case_id: s for s in scores}
    a = by_case["co-pt-loading-a"]
    assert a.predictor == "null"
    assert a.t50_mae_K == pytest.approx(45.125)
    assert a.band_coverage == pytest.approx(0.75)
    assert a.spearman is None and not a.trend_ok

    table = (tmp_path / "scores.md").read_text()
    assert "co-pt-loading-a" in table and "trend_ok" in table
    printed = capsys.readouterr().out
    assert "co-pt-loading-a" in printed  # the table is printed too


def test_baseline_predictor_needs_model(tmp_path, capsys):
    cards, _ = build(tmp_path)
    rc = cli.main(["baseline", str(cards), "--predictor", "baseline", "-o", str(tmp_path / "p.jsonl")])
    assert rc == 1
    assert "co_lightoff" in capsys.readouterr().err
