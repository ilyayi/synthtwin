"""Sweep baselines: null (anchor everywhere, +-30 % relative band) and
model_predict (calibrate on the anchor, predict with point conditions),
plus load_sweep_model."""
from __future__ import annotations

import pytest

from synthtwin.core.schemas import Band
from synthtwin.lib.sweep import load_sweep_model, model_predict, null_predict, score_sweep


def test_null_predict(sweep_a):
    card, _ = sweep_a
    pred = null_predict(card)
    assert pred.predictor == "null"
    assert pred.case_id == card.case_id
    assert list(pred.points) == [p.label for p in card.points]
    for bands in pred.points.values():
        assert set(bands) == {"size_mean_nm", "size_cv_pct"}
        size = bands["size_mean_nm"]
        assert size.value == 18.0  # the anchor outcome, everywhere
        assert size.low == pytest.approx(18.0 - 0.3 * 18.0)
        assert size.high == pytest.approx(18.0 + 0.3 * 18.0)
        assert size.unit == "nm"
        cv = bands["size_cv_pct"]
        assert (cv.value, cv.low, cv.high) == (19.0, pytest.approx(13.3), pytest.approx(24.7))


def test_model_predict_calibrates_on_anchor(sweep_a):
    card, _ = sweep_a
    calls = {"calibrate": [], "predict": []}

    class Recording:
        def calibrate(self, params, outcomes):
            calls["calibrate"].append((dict(params), dict(outcomes)))
            return {"size_scale": 2.0}

        def predict(self, params):
            calls["predict"].append(dict(params))
            return {"size_mean_nm": {"value": 20.0, "low": 18.0, "high": 22.0, "unit": "nm"}}

    pred = model_predict(card, Recording().predict, Recording().calibrate)
    assert pred.predictor == "baseline"
    cal_params, cal_outcomes = calls["calibrate"][0]
    anchor = next(p for p in card.points if p.label == card.anchor_label)
    assert cal_params == anchor.conditions  # the anchor's conditions
    assert cal_outcomes == {"size_mean_nm": 18.0, "size_cv_pct": 19.0}
    # one predict per point, in card order, each carrying the calibrated knob
    assert calls["predict"] == [
        {**p.conditions, "size_scale": 2.0} for p in card.points
    ]
    last = next(p for p in card.points if p.label == "r20")
    assert calls["predict"][-1] == {**last.conditions, "size_scale": 2.0}
    assert pred.points["r20"]["size_mean_nm"] == Band(
        value=20.0, low=18.0, high=22.0, unit="nm"
    )


def test_model_predict_calibrate_none(sweep_a):
    """A simulator with nothing to calibrate may return None."""
    card, _ = sweep_a
    pred = model_predict(
        card,
        lambda p: {"size_mean_nm": {"value": 10.0, "low": 8.0, "high": 12.0, "unit": "nm"}},
        lambda p, o: None,
    )
    assert pred.points["r10"]["size_mean_nm"].value == 10.0


def test_model_predict_stub_trend(sweep_a):
    """The stub (tests/stub_np_model.py) reproduces the anchor exactly and the
    measured size trend, so size_mean_nm is trend_ok; the quantity it does
    not predict is incomplete and never trend_ok."""
    from stub_np_model import StubNp

    card, vault = sweep_a
    stub = StubNp()
    pred = model_predict(card, stub.predict, stub.calibrate)
    anchor_band = pred.points[card.anchor_label]["size_mean_nm"]
    assert anchor_band.value == pytest.approx(18.0)  # calibrated on the anchor
    scores = {s.quantity: s for s in score_sweep(card, vault, pred)}
    assert scores["size_mean_nm"].spearman == pytest.approx(1.0)
    assert scores["size_mean_nm"].trend_ok
    assert not scores["size_cv_pct"].trend_ok
    assert scores["size_cv_pct"].band_coverage == pytest.approx(0.0)


def test_load_sweep_model():
    from stub_np_model import make_model

    predict, calibrate = load_sweep_model("stub_np_model:make_model")
    assert predict({"ratio_reductant_precursor": 5.0, "size_scale": 1.0})[
        "size_mean_nm"
    ]["value"] == pytest.approx(30.0 * 5.0 ** -0.7)
    assert calibrate({"ratio_reductant_precursor": 5.0}, {"size_mean_nm": 18.0}) == {
        "size_scale": pytest.approx(18.0 / (30.0 * 5.0 ** -0.7))
    }


def test_load_sweep_model_rejects_bad_spec():
    for spec in (None, "", "stub_np_model"):
        with pytest.raises(ImportError, match="package.module:function"):
            load_sweep_model(spec)
