"""Search the problem's knobs with the calibrated simulator.

optimize.run samples a Latin hypercube over the knob bounds, scores every point
with the objective below, refines the best few starts with L-BFGS-B and returns
the top candidates, spread out in knob space so the proposer has real choices.
Deterministic per seed. Called by run.main.

Objective per target quantity (weight w, predicted value v with band [lo, hi],
scale s = max(|aim|, |v|)):
    w * ((v - aim) / s)^2                     aim target
  + w * ((edge - limit) / s)^2                min/max violated, edge = band lo/hi
  + 0.05 * ((hi - lo) / 2 / s)^2              small penalty for wide bands
Missing quantities are skipped (and noted on the candidate).
"""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy.optimize import minimize
from scipy.stats import qmc

from synthtwin.core.schemas import Band, Candidate, Problem
from synthtwin.lib.design.calibrate import Calibration

WIDE_BAND_WEIGHT = 0.05        # the "small term for wide bands"
N_REFINE = 6                   # LHS starts refined with L-BFGS-B
DIVERSITY_MIN_DISTANCE = 0.12  # min knob-space distance (unit cube) between candidates


def run(
    problem: Problem,
    predictor: Any,
    calibration: Calibration,
    seed: int = 0,
    n_eval: int = 80,
    validated: dict[str, dict[str, list[float]]] | None = None,
) -> list[Candidate]:
    """-> up to 3 x problem.n_proposals diverse Candidates, best first."""
    names = sorted(problem.knobs)
    lo = np.array([problem.knobs[k][0] for k in names])
    hi = np.array([problem.knobs[k][1] for k in names])
    method = problem.methods[0] if problem.methods else ""
    cache: dict[tuple[float, ...], tuple[float, dict[str, Any]]] = {}

    def evaluate(x: np.ndarray) -> tuple[float, dict[str, Any]]:
        key = tuple(float(f) for f in np.round(x, 9))
        if key not in cache:
            conditions = {**problem.fixed, **dict(zip(names, (float(v) for v in x)))}
            params = {
                "material": problem.material,
                "method": method,
                "conditions": conditions,
                "reagents": [],
                "calibration": calibration.params or None,
            }
            try:
                raw = predictor.predict(params)
                score = _objective(problem, raw)
            except Exception:  # a point the simulator rejects is infeasible, not fatal
                raw, score = {}, float("inf")
            cache[key] = (score, raw)
        return cache[key]

    sampler = qmc.LatinHypercube(d=len(names), seed=seed)
    points = lo + (hi - lo) * sampler.random(n_eval)
    for x in points:
        evaluate(x)

    starts = _best_starts(cache, points, lo, hi, n=N_REFINE)
    for x0 in starts:
        minimize(
            lambda x: evaluate(np.asarray(x))[0], x0, method="L-BFGS-B",
            bounds=list(zip(lo, hi)),
        )

    # refined points are in the cache too (evaluate is the only path in)
    order = sorted(cache.items(), key=lambda kv: kv[1][0])
    scored = [
        (np.array(k), score, raw) for k, (score, raw) in order if np.isfinite(score)
    ]
    wanted = 3 * problem.n_proposals
    picked = _select_diverse([s[0] for s in scored], lo, hi, wanted)

    candidates: list[Candidate] = []
    for i in picked:
        x, score, raw = scored[i]
        conditions = {**problem.fixed, **dict(zip(names, (float(v) for v in x)))}
        ok, note = _in_validated(conditions, method, validated, names)
        missing = [q for q in problem.targets if q not in raw]
        notes = [note] if note else []
        if missing:
            notes.append(f"predictor reports no band for {', '.join(missing)}")
        candidates.append(
            Candidate(
                method=method,
                conditions=conditions,
                predicted={q: _widen(b, calibration.band_factor) for q, b in raw.items()},
                score=round(score, 6),
                in_validated_region=ok,
                notes=notes,
            )
        )
    return candidates


def _objective(problem: Problem, bands: dict[str, Any]) -> float:
    total = 0.0
    for quantity, target in problem.targets.items():
        b = bands.get(quantity)
        if b is None:
            continue
        v, low, high = float(b["value"]), float(b["low"]), float(b["high"])
        scale = _scale(target, v)
        if target.value is not None:
            total += target.weight * ((v - target.value) / scale) ** 2
        if target.min is not None and low < target.min:
            total += target.weight * ((target.min - low) / scale) ** 2
        if target.max is not None and high > target.max:
            total += target.weight * ((high - target.max) / scale) ** 2
        total += WIDE_BAND_WEIGHT * ((high - low) / 2.0 / scale) ** 2
    return total


def _scale(target: Any, v: float) -> float:
    ref = next(x for x in (target.value, target.min, target.max) if x is not None)
    return max(abs(ref), abs(v), 1e-9)


def _best_starts(
    cache: dict[tuple[float, ...], tuple[float, dict[str, Any]]],
    points: np.ndarray,
    lo: np.ndarray,
    hi: np.ndarray,
    n: int,
) -> list[np.ndarray]:
    """Distinct LHS points with the best scores, for local refinement."""
    seen: list[tuple[float, np.ndarray]] = []
    for x in points:
        key = tuple(float(f) for f in np.round(x, 9))
        score = cache[key][0]
        if not np.isfinite(score):
            continue
        if any(np.array_equal(x, y) for _, y in seen):
            continue
        seen.append((score, x))
    seen.sort(key=lambda t: t[0])
    return [x for _, x in seen[:n]]


def _select_diverse(points: list[np.ndarray], lo: np.ndarray, hi: np.ndarray, count: int) -> list[int]:
    """Best-first indices at least DIVERSITY_MIN_DISTANCE apart (unit cube);
    topped up with the best remaining when space runs out. Points arrive
    score-sorted, so index order is rank order."""
    unit = np.array([(p - lo) / (hi - lo) for p in points])
    chosen: list[int] = []
    for i in range(len(points)):
        if len(chosen) >= count:
            break
        if all(np.linalg.norm(unit[i] - unit[j]) >= DIVERSITY_MIN_DISTANCE for j in chosen):
            chosen.append(i)
    for i in range(len(points)):
        if len(chosen) >= count:
            break
        if i not in chosen:
            chosen.append(i)
    return chosen


def _in_validated(
    conditions: dict[str, float],
    method: str,
    validated: dict[str, dict[str, list[float]]] | None,
    knob_names: list[str],
) -> tuple[bool, str]:
    ranges = (validated or {}).get(method)
    if not ranges:
        return False, (
            f"no validated ranges for method '{method}'; labelled exploratory"
            if method else "no method and no validated ranges; labelled exploratory"
        )
    for knob in knob_names:
        if knob not in ranges:
            return False, f"knob '{knob}' not in the validated ranges for '{method}'"
        lo, hi = ranges[knob]
        v = conditions.get(knob)
        if v is None or not (lo <= v <= hi):
            return False, (
                f"knob '{knob}' = {v:.2f} outside the validated range "
                f"[{lo:g}, {hi:g}] for '{method}'"
            )
    return True, ""


def _widen(band: dict[str, Any], factor: float) -> Band:
    """Predictor band -> Band with half-width x factor (calibration spread)."""
    v, low, high = float(band["value"]), float(band["low"]), float(band["high"])
    half = (high - low) / 2.0 * factor
    return Band(value=v, low=v - half, high=v + half, unit=str(band.get("unit", "")))
