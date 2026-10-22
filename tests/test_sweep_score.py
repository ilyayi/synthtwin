"""score_sweep tests with hand-computed spearman / MAE / coverage numbers,
per quantity. Case A measured (np-au-citrate-a):

  size_mean_nm:  r1 42.0, r2p5 28.5, r5 18.0 (anchor), r10 12.5, r20 9.0
  size_cv_pct:   r1 28.0, r2p5 23.0, r5 19.0 (anchor), r10 16.0, r20 14.0
"""
from __future__ import annotations

import pytest

from synthtwin.core.schemas import Band, SweepPrediction
from synthtwin.lib.sweep import null_predict, score_sweep

QUANTITIES = ("size_mean_nm", "size_cv_pct")


def predict(card, per_label, band=1.0):
    """SweepPrediction from {label: {quantity: value}} with a +-band."""
    return SweepPrediction(
        case_id=card.case_id,
        predictor="agent:test",
        points={
            label: {
                q: Band(value=v, low=v - band, high=v + band, unit="x")
                for q, v in quants.items()
            }
            for label, quants in per_label.items()
        },
    )


def by_quantity(scores):
    return {s.quantity: s for s in scores}


def test_perfect_prediction(sweep_a):
    card, vault = sweep_a
    pred = predict(
        card,
        {
            "r1": {"size_mean_nm": 42.0, "size_cv_pct": 28.0},
            "r2p5": {"size_mean_nm": 28.5, "size_cv_pct": 23.0},
            "r5": {"size_mean_nm": 18.0, "size_cv_pct": 19.0},
            "r10": {"size_mean_nm": 12.5, "size_cv_pct": 16.0},
            "r20": {"size_mean_nm": 9.0, "size_cv_pct": 14.0},
        },
    )
    scores = by_quantity(score_sweep(card, vault, pred))
    assert set(scores) == set(QUANTITIES)
    for q in QUANTITIES:
        s = scores[q]
        assert s.spearman == pytest.approx(1.0)
        assert s.mae == pytest.approx(0.0)
        assert s.band_coverage == pytest.approx(1.0)
        assert s.trend_ok
        assert s.n_points == 4
        assert s.predictor == "agent:test" and s.case_id == card.case_id


def test_null_scores_hand_computed(sweep_a):
    """Anchor value everywhere: constant prediction -> spearman None, and the
    +-30 % relative band from null_predict.

    size: |18-x| over 42, 28.5, 12.5, 9 = 49/4 = 12.25; band [12.6, 23.4]
    covers none of them.  cv: |19-x| over 28, 23, 16, 14 = 21/4 = 5.25; band
    [13.3, 24.7] covers 23, 16, 14 but not 28."""
    card, vault = sweep_a
    scores = by_quantity(score_sweep(card, vault, null_predict(card)))
    size, cv = scores["size_mean_nm"], scores["size_cv_pct"]
    assert size.predictor == "null" and cv.predictor == "null"
    for s in (size, cv):
        assert s.spearman is None
        assert not s.trend_ok
    assert size.mae == pytest.approx(12.25)
    assert size.band_coverage == pytest.approx(0.0)
    assert cv.mae == pytest.approx(5.25)
    assert cv.band_coverage == pytest.approx(0.75)


def test_spearman_point_nine(sweep_a):
    card, vault = sweep_a
    # swap the two largest sizes -> ranks [4,5,3,2,1] vs [5,4,3,2,1]
    pred = predict(
        card,
        {
            "r1": {"size_mean_nm": 28.5, "size_cv_pct": 28.0},
            "r2p5": {"size_mean_nm": 42.0, "size_cv_pct": 23.0},
            "r5": {"size_mean_nm": 18.0, "size_cv_pct": 19.0},
            "r10": {"size_mean_nm": 12.5, "size_cv_pct": 16.0},
            "r20": {"size_mean_nm": 9.0, "size_cv_pct": 14.0},
        },
    )
    s = by_quantity(score_sweep(card, vault, pred))["size_mean_nm"]
    assert s.spearman == pytest.approx(0.9)
    assert s.trend_ok  # n >= 4 and spearman >= 0.8


def test_reversed_prediction(sweep_a):
    card, vault = sweep_a
    pred = predict(
        card,
        {
            "r1": {"size_mean_nm": 9.0, "size_cv_pct": 14.0},
            "r2p5": {"size_mean_nm": 12.5, "size_cv_pct": 16.0},
            "r5": {"size_mean_nm": 18.0, "size_cv_pct": 19.0},
            "r10": {"size_mean_nm": 28.5, "size_cv_pct": 23.0},
            "r20": {"size_mean_nm": 42.0, "size_cv_pct": 28.0},
        },
    )
    scores = by_quantity(score_sweep(card, vault, pred))
    for q in QUANTITIES:
        assert scores[q].spearman == pytest.approx(-1.0)
        assert not scores[q].trend_ok
    # (33 + 16 + 16 + 33) / 4
    assert scores["size_mean_nm"].mae == pytest.approx(24.5)


def test_exact_order_short_case(sweep_c):
    """n = 3: trend_ok is exact rank order, not the 0.8 spearman threshold."""
    card, vault = sweep_c
    good = predict(
        card,
        {
            "s0.005": {"size_mean_nm": 45.0, "dls_z_nm": 52.0},
            "s0.010": {"size_mean_nm": 30.0, "dls_z_nm": 35.0},
            "s0.020": {"size_mean_nm": 22.0, "dls_z_nm": 26.0},
        },
    )
    assert all(s.trend_ok for s in score_sweep(card, vault, good))
    # swap the anchor: spearman 0.5 but n < 4 so only the order matters
    swapped = predict(
        card,
        {
            "s0.005": {"size_mean_nm": 45.0, "dls_z_nm": 52.0},
            "s0.010": {"size_mean_nm": 22.0, "dls_z_nm": 26.0},
            "s0.020": {"size_mean_nm": 30.0, "dls_z_nm": 35.0},
        },
    )
    s = by_quantity(score_sweep(card, vault, swapped))["size_mean_nm"]
    assert s.spearman == pytest.approx(0.5)
    assert not s.trend_ok


def test_missing_quantity_at_one_point(sweep_a):
    """cv missing at r20: that quantity is incomplete - never trend_ok, and
    the skipped point counts as a coverage miss (3/4, not 3/3)."""
    card, vault = sweep_a
    pred = predict(
        card,
        {
            "r1": {"size_mean_nm": 42.0, "size_cv_pct": 28.0},
            "r2p5": {"size_mean_nm": 28.5, "size_cv_pct": 23.0},
            "r5": {"size_mean_nm": 18.0, "size_cv_pct": 19.0},
            "r10": {"size_mean_nm": 12.5, "size_cv_pct": 16.0},
            "r20": {"size_mean_nm": 9.0},
        },
    )
    scores = by_quantity(score_sweep(card, vault, pred))
    assert scores["size_mean_nm"].trend_ok
    cv = scores["size_cv_pct"]
    assert not cv.trend_ok
    assert cv.spearman == pytest.approx(1.0)  # order still perfect on 4 points
    assert cv.band_coverage == pytest.approx(0.75)
    # mae over the three predicted held-out points only
    assert cv.mae == pytest.approx(0.0)


def test_constant_measured_no_spearman(sweep_a):
    card, vault = sweep_a
    flat = vault.model_copy(deep=True)
    for outcomes in flat.outcomes.values():
        for o in outcomes:
            if o.quantity == "size_mean_nm":
                o.value = 18.0
    pred = predict(card, {p.label: {"size_mean_nm": float(i), "size_cv_pct": 19.0}
                          for i, p in enumerate(card.points)})
    s = by_quantity(score_sweep(card, flat, pred))["size_mean_nm"]
    assert s.spearman is None


def test_extra_prediction_quantity_ignored(sweep_a):
    card, vault = sweep_a
    pred = null_predict(card)
    pred.points["r1"]["dls_z_nm"] = Band(value=50.0, low=45.0, high=55.0, unit="nm")
    scores = score_sweep(card, vault, pred)
    assert [s.quantity for s in scores] == list(card.quantities)
