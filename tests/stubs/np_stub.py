"""Stub nanoparticle simulator for tests (contract: predict + calibrate).

Size falls with ratio_reductant_precursor and temperature; CV falls with
temperature. calibrate fits one multiplicative size_scale on the outcomes it is
given. Deterministic; no state. Loaded by tests as `--predictor np_stub`
(tests/stubs is put on sys.path by conftest).
"""
from __future__ import annotations

import statistics
from typing import Any


def _conditions(params: dict[str, Any]) -> dict[str, float]:
    return {k: float(v) for k, v in (params.get("conditions") or {}).items()}


def _size_nm(conditions: dict[str, float], scale: float) -> float:
    ratio = conditions.get("ratio_reductant_precursor", 3.0)
    temp = conditions.get("temperature_C", 90.0)
    conc = conditions.get("conc_precursor_mM", 0.5)
    raw = 45.0 * ratio ** -0.7 * (temp / 100.0) ** -1.5 * (conc / 0.5) ** 0.15
    return raw * scale


def _cv_pct(conditions: dict[str, float]) -> float:
    temp = conditions.get("temperature_C", 90.0)
    return 8.0 * (100.0 / temp) ** 1.5


def predict(params: dict[str, Any]) -> dict[str, dict[str, Any]]:
    conditions = _conditions(params)
    scale = float((params.get("calibration") or {}).get("size_scale", 1.0))
    size = _size_nm(conditions, scale)
    cv = _cv_pct(conditions)
    lspr = 517.0 + 0.35 * size
    dls = 1.12 * size
    pdi = (cv / 100.0) ** 2 + 0.03
    return {
        "size_mean_nm": _band(size, 0.05, "nm"),
        "size_cv_pct": _band(cv, 0.07, "%"),
        "lspr_nm": _band(lspr, 0.02, "nm"),
        "dls_z_nm": _band(dls, 0.08, "nm"),
        "dls_pdi": _band(pdi, 0.15, ""),
    }


def _band(value: float, rel: float, unit: str) -> dict[str, Any]:
    return {"value": value, "low": value * (1 - rel), "high": value * (1 + rel), "unit": unit}


def calibrate(params: dict[str, Any], outcomes: list[Any]) -> dict[str, Any]:
    """Fit size_scale = measured size / modelled size (median over size outcomes)."""
    conditions = _conditions(params)
    ratios = [
        float(o.value) / _size_nm(conditions, 1.0)
        for o in outcomes
        if o.quantity == "size_mean_nm" and o.value
    ]
    if not ratios:
        return {}
    return {"size_scale": statistics.median(ratios)}
