"""Null and physics-baseline SynthTwin predictors (CasePrediction interface).

The null predictor answers "the anchor everywhere" - the floor any real model
must beat. The baseline maps a CaseCard onto a co_lightoff-style model
(predict_lightoff), calibrates log10_site_scale on the anchor point, then
predicts every point with that scale. Called by the CLI (baseline) and the
evaluation harness to fill the scoreboard's comparison rows.
"""
from __future__ import annotations

from typing import Any, Callable

from scipy.optimize import brentq

from synthtwin.schemas import CaseCard, CasePrediction, PointPrediction, SweepPoint

RunLightoff = Callable[[dict[str, Any]], dict[str, Any]]

# bracket for numeric log10_site_scale inversion when the model does not
# report the scale it calibrated itself (see _invert_scale)
_SCALE_LO, _SCALE_HI, _SCALE_STEP = -6.0, 6.0, 0.5


def null_predict(card: CaseCard) -> CasePrediction:
    """Every point = the revealed anchor T50, band +-50 K."""
    t50 = card.anchor_t50_K
    points = [
        PointPrediction(label=p.label, t50_K=t50, low_K=t50 - 50.0, high_K=t50 + 50.0)
        for p in card.points
    ]
    return CasePrediction(case_id=card.case_id, points=points, predictor="null")


def baseline_predict(card: CaseCard, run_lightoff: RunLightoff) -> CasePrediction:
    """Calibrate log10_site_scale on the anchor, then predict every point."""
    anchor_point = next(p for p in card.points if p.label == card.anchor_label)
    scale = _calibrate(card, anchor_point, run_lightoff)
    points = []
    for p in card.points:
        res = run_lightoff(_params(card, p, log10_site_scale=scale))
        points.append(
            PointPrediction(
                label=p.label,
                t50_K=float(res["t50_K"]),
                low_K=float(res["t50_K_low"]),
                high_K=float(res["t50_K_high"]),
            )
        )
    return CasePrediction(case_id=card.case_id, points=points, predictor="baseline")


def _params(
    card: CaseCard,
    point: SweepPoint,
    log10_site_scale: float | None,
    calibrate_t50_K: float | None = None,
) -> dict[str, Any]:
    """Card -> co_lightoff params. Per-point: metal, loading, dispersion (or
    particle_nm) and the swept variable; global: mass, flow/ghsv, feed."""
    params: dict[str, Any] = {"metal": point.catalyst.metal}
    if point.catalyst.loading_wt_pct is not None:
        params["loading_wt_pct"] = point.catalyst.loading_wt_pct
    if point.catalyst.dispersion is not None:
        params["dispersion"] = point.catalyst.dispersion
    elif point.catalyst.particle_nm is not None:
        params["particle_nm"] = point.catalyst.particle_nm
    if card.catalyst_mass_mg is not None:
        params["catalyst_mass_mg"] = card.catalyst_mass_mg
    if card.flow_ml_min is not None:
        params["flow_ml_min"] = card.flow_ml_min
    if card.ghsv_per_h is not None:
        params["ghsv_per_h"] = card.ghsv_per_h
    if card.feed.co_pct is not None:
        params["co_pct"] = card.feed.co_pct
    if card.feed.o2_pct is not None:
        params["o2_pct"] = card.feed.o2_pct
    params[card.sweep_variable] = point.value  # the swept value per point
    if log10_site_scale is not None:
        params["log10_site_scale"] = log10_site_scale
    if calibrate_t50_K is not None:
        params["calibrate_t50_K"] = calibrate_t50_K
    return params


def _calibrate(card: CaseCard, anchor_point: SweepPoint, run_lightoff: RunLightoff) -> float:
    """Find log10_site_scale that puts the anchor's T50 on the measured one.

    Primary path: pass calibrate_t50_K and read the scale the model reports
    under log10_site_scale_used (see README, "Use"). Fallback:
    invert t50_K(log10_site_scale) numerically with brentq."""
    res = run_lightoff(
        _params(card, anchor_point, log10_site_scale=None, calibrate_t50_K=card.anchor_t50_K)
    )
    scale = res.get("log10_site_scale_used") if isinstance(res, dict) else None
    if scale is not None:
        return float(scale)
    return _invert_scale(card, anchor_point, run_lightoff)


def _invert_scale(card: CaseCard, point: SweepPoint, run_lightoff: RunLightoff) -> float:
    def f(s: float) -> float:
        res = run_lightoff(_params(card, point, log10_site_scale=s))
        return float(res["t50_K"]) - card.anchor_t50_K

    n_steps = int(round((_SCALE_HI - _SCALE_LO) / _SCALE_STEP))
    a, fa = _SCALE_LO, f(_SCALE_LO)
    for i in range(1, n_steps + 1):
        b = _SCALE_LO + i * _SCALE_STEP
        fb = f(b)
        if fa == 0.0:
            return a
        if fa * fb < 0:
            return float(brentq(f, a, b))
        a, fa = b, fb
    # no sign change anywhere in the bracket: the model ignores the scale
    return 0.0
