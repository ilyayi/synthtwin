"""Baseline predictors: null everywhere-anchor, and a stub run_lightoff
(monotone in loading) driving baseline_predict through both calibration
paths (model-reported scale and numeric inversion)."""
from __future__ import annotations

import math

import pytest

from synthtwin.baseline import baseline_predict, null_predict
from synthtwin.score import score


def stub_lightoff(params):
    """Fake co_lightoff: T50 = 500 K - 25 * log10(loading * site_scale).
    Honors calibrate_t50_K by reporting the solved scale under
    log10_site_scale_used (the model contract key)."""
    loading = params.get("loading_wt_pct", 1.0)
    if "calibrate_t50_K" in params:
        t50 = params["calibrate_t50_K"]
        s = (500.0 - t50) / 25.0 - math.log10(loading)
    else:
        s = params.get("log10_site_scale", 0.0)
        t50 = 500.0 - 25.0 * (math.log10(loading) + s)
    return {
        "t50_K": t50,
        "t50_K_low": t50 - 12.0,
        "t50_K_high": t50 + 12.0,
        "log10_site_scale_used": s,
    }


def stub_no_scale(params):
    """Same physics, but never reports its scale -> forces brentq inversion."""
    loading = params.get("loading_wt_pct", 1.0)
    s = params.get("log10_site_scale", 0.0)
    t50 = 500.0 - 25.0 * (math.log10(loading) + s)
    return {"t50_K": t50, "t50_K_low": t50 - 12.0, "t50_K_high": t50 + 12.0}


def test_null_predict(case_a):
    card, _ = case_a
    pred = null_predict(card)
    assert pred.predictor == "null"
    assert pred.case_id == card.case_id
    assert [p.label for p in pred.points] == [p.label for p in card.points]
    assert all(
        p.t50_K == card.anchor_t50_K
        and p.low_K == card.anchor_t50_K - 50.0
        and p.high_K == card.anchor_t50_K + 50.0
        for p in pred.points
    )


def test_baseline_calibrates_on_anchor(case_a):
    card, _ = case_a
    calls = []

    def recording_stub(params):
        calls.append(dict(params))
        return stub_lightoff(params)

    pred = baseline_predict(card, recording_stub)
    assert pred.predictor == "baseline"
    anchor = next(p for p in pred.points if p.label == card.anchor_label)
    assert anchor.t50_K == pytest.approx(card.anchor_t50_K, abs=1e-9)
    assert all(p.low_K < p.t50_K < p.high_K for p in pred.points)
    # the scale reported by the calibrate call is fixed and propagated to
    # every prediction call
    (cal,) = (c for c in calls if "calibrate_t50_K" in c)
    others = [c for c in calls if "calibrate_t50_K" not in c]
    scale = stub_lightoff(cal)["log10_site_scale_used"]
    assert others and all(c.get("log10_site_scale") == scale for c in others)


def test_baseline_monotone_stub_trend_ok(case_a):
    card, vault = case_a
    pred = baseline_predict(card, stub_lightoff)
    s = score(card, vault, pred)
    assert s.spearman == pytest.approx(1.0)
    assert s.trend_ok


def test_baseline_numeric_calibration(case_a):
    """Model does not report its scale: brentq inversion over log10_site_scale."""
    card, vault = case_a
    pred = baseline_predict(card, stub_no_scale)
    anchor = next(p for p in pred.points if p.label == card.anchor_label)
    assert anchor.t50_K == pytest.approx(card.anchor_t50_K, abs=1e-6)
    assert score(card, vault, pred).trend_ok


def test_baseline_params_reach_stub(case_a, case_b):
    card, _ = case_b  # sweeps particle_nm, sets ghsv instead of flow
    calls = []

    def recorder(params):
        calls.append(dict(params))
        return {"t50_K": 450.0, "t50_K_low": 440.0, "t50_K_high": 460.0}

    baseline_predict(card, recorder)
    cal = next(c for c in calls if "calibrate_t50_K" in c)
    assert cal["metal"] == "Pd"
    assert "dispersion" not in cal  # particle branch used instead
    assert cal["particle_nm"] == 5  # anchor point: lower median of [2, 5, 10, 20]
    assert cal["ghsv_per_h"] == 60000.0
    assert "flow_ml_min" not in cal
    assert cal["co_pct"] == 2.0 and cal["o2_pct"] == 10.0
    assert cal["catalyst_mass_mg"] == 25.0
    assert cal["calibrate_t50_K"] == 445.0
    last = calls[-1]
    assert last["particle_nm"] == 20 and "calibrate_t50_K" not in last
    assert "log10_site_scale" in last
