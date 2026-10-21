"""score() tests with hand-computed spearman / MAE / coverage numbers."""
from __future__ import annotations

import pytest

from synthtwin.schemas import (
    CaseCard,
    CasePrediction,
    Catalyst,
    Feed,
    MeasuredPoint,
    PointPrediction,
    SweepPoint,
    VaultEntry,
)
from synthtwin.score import score

# case A measured: 0.1Pt 520.0, 0.5Pt 470.5, 1.0Pt 440.0 (anchor),
#                   2.0Pt 415.0, 5.0Pt 395.0


def predict(card, values, band=10.0):
    """CasePrediction with per-label values (label -> t50 K) and a +-band."""
    return CasePrediction(
        case_id=card.case_id,
        predictor="agent:test",
        points=[
            PointPrediction(label=l, t50_K=t, low_K=t - band, high_K=t + band)
            for l, t in values.items()
        ],
    )


def test_perfect_prediction(case_a):
    card, vault = case_a
    pred = predict(
        card,
        {"0.1Pt": 520.0, "0.5Pt": 470.5, "1.0Pt": 440.0, "2.0Pt": 415.0, "5.0Pt": 395.0},
    )
    s = score(card, vault, pred)
    assert s.spearman == pytest.approx(1.0)
    assert s.t50_mae_K == pytest.approx(0.0)
    assert s.band_coverage == pytest.approx(1.0)
    assert s.trend_ok
    assert s.n_points == 4
    assert s.predictor == "agent:test" and s.case_id == card.case_id


def test_null_score_hand_computed(case_a):
    """All points at the anchor 440 K: constant input -> spearman None."""
    card, vault = case_a
    pred = predict(card, {p.label: 440.0 for p in card.points}, band=50.0)
    s = score(card, vault, pred)
    assert s.spearman is None
    # |440-520| + |440-470.5| + |440-415| + |440-395| = 180.5 over 4 points
    assert s.t50_mae_K == pytest.approx(45.125)
    # bands [390, 490]: 470.5, 415, 395 inside; 520 outside
    assert s.band_coverage == pytest.approx(0.75)
    assert not s.trend_ok


def test_spearman_point_nine(case_a):
    card, vault = case_a
    # swap the two lowest-loading predictions -> ranks [4,5,3,2,1] vs [5,4,3,2,1]
    pred = predict(
        card,
        {"0.1Pt": 460.0, "0.5Pt": 510.0, "1.0Pt": 440.0, "2.0Pt": 430.0, "5.0Pt": 400.0},
    )
    s = score(card, vault, pred)
    assert s.spearman == pytest.approx(0.9)
    assert s.trend_ok  # n >= 4 and spearman >= 0.8


def test_reversed_prediction(case_a):
    card, vault = case_a
    pred = predict(
        card,
        {"0.1Pt": 395.0, "0.5Pt": 415.0, "1.0Pt": 440.0, "2.0Pt": 470.5, "5.0Pt": 520.0},
    )
    s = score(card, vault, pred)
    assert s.spearman == pytest.approx(-1.0)
    assert not s.trend_ok
    # (125 + 55.5 + 55.5 + 125) / 4
    assert s.t50_mae_K == pytest.approx(90.25)


def test_exact_order_short_case(case_c):
    """n = 3: trend_ok is exact rank order, not the 0.8 spearman threshold."""
    card, vault = case_c
    good = predict(card, {"D20": 480.0, "D50": 455.0, "D80": 435.0})
    assert score(card, vault, good).trend_ok
    # swap the anchor: spearman 0.5 < 0.8 but n < 4 so only order matters
    swapped = predict(card, {"D20": 480.0, "D50": 425.0, "D80": 435.0})
    s = score(card, vault, swapped)
    assert s.spearman == pytest.approx(0.5)
    assert not s.trend_ok


def test_two_points_no_spearman():
    card = CaseCard(
        case_id="mini",
        paper_title="mini", paper_url="https://x", licence="CC0",
        published="2020", post_cutoff=False, sweep_variable="loading_wt_pct",
        points=[
            SweepPoint(label="a", value=1.0, catalyst=Catalyst(metal="Pt", support="Al2O3")),
            SweepPoint(label="b", value=2.0, catalyst=Catalyst(metal="Pt", support="Al2O3")),
        ],
        feed=Feed(), anchor_label="a", anchor_t50_K=400.0,
    )
    vault = VaultEntry(
        case_id="mini",
        points=[MeasuredPoint(label="a", t50_K=400.0), MeasuredPoint(label="b", t50_K=380.0)],
        digitised_by=["x"], canary="c" * 16,
    )
    same_order = CasePrediction(
        case_id="mini", predictor="agent:test",
        points=[PointPrediction(label="a", t50_K=400.0, low_K=390.0, high_K=410.0),
                PointPrediction(label="b", t50_K=390.0, low_K=380.0, high_K=400.0)],
    )
    s = score(card, vault, same_order)
    assert s.spearman is None  # n < 3
    assert s.trend_ok  # ranks [2,1] vs [2,1]
    assert s.t50_mae_K == pytest.approx(10.0)
    assert s.band_coverage == pytest.approx(1.0)
    assert s.n_points == 1

    flipped = same_order.model_copy(deep=True)
    flipped.points[0].t50_K = 390.0
    flipped.points[1].t50_K = 400.0
    assert not score(card, vault, flipped).trend_ok
