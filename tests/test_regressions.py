"""Regression tests: leak scan at sentence ends, vault created private,
incomplete predictions never score as trend_ok."""
import stat

from synthtwin.schemas import CasePrediction, PointPrediction
from synthtwin.score import score as score_fn
from synthtwin.vault import leak_scan, write_vault


def test_leak_scan_integer_at_sentence_end(tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("T50 was 448. Then 470. Finally 520.")
    assert leak_scan([f], "canary", [448.0, 470.0, 520.0])
    f.write_text("448.3 and 470.4 and 520.6")
    assert not leak_scan([f], "canary", [448.0, 470.0, 520.0])


def test_vault_file_created_private(case_a, tmp_path):
    _card, entry = case_a
    path = write_vault(tmp_path / "vault", entry)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_incomplete_prediction_not_trend_ok(case_a):
    card, entry = case_a
    t = card.anchor_t50_K
    pred = CasePrediction(case_id=card.case_id, predictor="x",
                          points=[PointPrediction(label=card.anchor_label, t50_K=t,
                                                  low_K=t - 10, high_K=t + 10)])
    s = score_fn(card, entry, pred)
    assert not s.trend_ok and s.band_coverage == 0.0
