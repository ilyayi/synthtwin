"""Built-in vs agent-built simulators.

A study runs on the built-in continuum model when it is an Au/Ag colloid
synthesis. Any other system is "generic": its goal uses its own vocabulary
(snake_case keys ending in a unit), the agent designs a stack for it, a
builder agent writes and runs the simulations and assembles a predictor
module, and the benchmark scores that module on held-out literature data.

Predictor contract (built-in and generated alike):

    predict(params) -> {quantity: {"value", "low", "high", "unit"}}
        params = {"material", "method", "conditions": {key: float},
                  "calibration": dict | None, "n_draws": int, ...}
    calibrate(params, outcomes) -> dict      (optional)
        outcomes: list of Outcome-like objects or {"quantity", "value"} dicts

A predictor is named by a module path ("synthtwin.lib.np.model") or a file
("file:/abs/path/model.py").
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import re
import sys
from types import ModuleType
from typing import Any

import numpy as np

NP_MATERIALS = ("Au", "Ag")
KEY = re.compile(r"^[a-z][a-z0-9]*(_[a-zA-Z0-9]+)*$")


def is_builtin(pb: dict) -> bool:
    """Au/Ag colloids run on the built-in model; everything else gets a built one."""
    return pb.get("system", "colloid") == "colloid" and pb.get("material") in NP_MATERIALS


def check_generic(pb: dict) -> list[str]:
    errs = []
    for k in [*(pb.get("knobs") or {}), *(pb.get("fixed") or {}), *(pb.get("targets") or {})]:
        if not KEY.match(k):
            errs.append(f"{k} is not a snake_case key with its unit (e.g. coating_speed_m_min)")
    return errs


# ---------------------------------------------------------------- loading
_cache: dict[str, ModuleType] = {}


def load(spec: str) -> ModuleType:
    if not spec.startswith("file:"):
        return importlib.import_module(spec)
    path = spec[5:]
    if path not in _cache:
        name = "st_built_" + hashlib.sha1(path.encode()).hexdigest()[:10]
        s = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(s)
        sys.modules[name] = mod
        sys.path.insert(0, str(__import__("pathlib").Path(path).parent))
        try:
            s.loader.exec_module(mod)
        finally:
            sys.path.pop(0)
        _cache[path] = mod
    return _cache[path]


def _band(b: Any) -> dict | None:
    if b is None:
        return None
    if not isinstance(b, dict):
        b = b.model_dump() if hasattr(b, "model_dump") else dict(b)
    try:
        v = float(b["value"])
    except (KeyError, TypeError, ValueError):
        return None
    if not np.isfinite(v):
        return None
    lo, hi = float(b.get("low", v)), float(b.get("high", v))
    return {"value": v, "low": min(lo, v), "high": max(hi, v), "unit": str(b.get("unit", ""))}


def predict(M: ModuleType, params: dict) -> dict:
    """Call a predictor and normalise its bands (generated code is not trusted to be tidy)."""
    out = M.predict(params) or {}
    return {q: b for q, b in ((q, _band(b)) for q, b in out.items()) if b}


# ---------------------------------------------------------------- generic benchmark
def run_case(card: dict, measured: dict | None, predictor: str, fixed: dict, blind: bool) -> dict:
    """Benchmark a built predictor on one held-out sweep: null, as built, and calibrated on the anchor."""
    from synthtwin.core.schemas import SweepCase, SweepPrediction, SweepVault
    from synthtwin.lib.sweep import null_predict, score_sweep
    M = load(predictor)
    case = SweepCase.model_validate(card)
    anchor = next(p for p in card["points"] if p["label"] == card["anchor_label"])
    base = {"material": card.get("material", ""), "method": card.get("method", ""), "n_draws": 16}
    preds: dict[str, dict] = {"null": {lbl: {q: b.model_dump() for q, b in bands.items()}
                                       for lbl, bands in null_predict(case).points.items()}}
    notes, cal_used = [], {}
    cals: dict[str, dict | None] = {"model": None}
    if hasattr(M, "calibrate"):
        try:
            cal = M.calibrate({**base, "conditions": {**fixed, **anchor["conditions"]}},
                              [{"quantity": o["quantity"], "value": o["value"]} for o in card["anchor_outcomes"]])
            cals["calibrated"] = cal or {}
            cal_used["calibrated"] = cal or {}
        except Exception as exc:
            notes.append(f"calibrate failed: {type(exc).__name__}: {exc}")
    for var, cal in cals.items():
        out = {}
        for p in card["points"]:
            try:
                res = predict(M, {**base, "conditions": {**fixed, **p["conditions"]}, "calibration": cal})
            except Exception as exc:
                notes.append(f"{var} {p['label']}: {type(exc).__name__}: {exc}"[:200])
                continue
            out[p["label"]] = {q: res[q] for q in card["quantities"] if q in res}
        preds[var] = out
    scores = []
    if measured:
        vault = SweepVault(case_id=card["case_id"], digitised_by=[], canary="",
                           outcomes={lbl: [{"quantity": q, "value": v, "unit": ""} for q, v in o.items()]
                                     for lbl, o in measured.items()})
        for var, pts in preds.items():
            sp = SweepPrediction(case_id=card["case_id"], predictor=var, points=pts)
            for s in score_sweep(case, vault, sp):
                scores.append({"variant": var, **s.model_dump(exclude={"case_id", "predictor"})})
    return {"case_id": card["case_id"], "title": card.get("paper_title", ""), "url": card.get("paper_url", ""),
            "sweep_variable": card["sweep_variable"], "quantities": card["quantities"], "blind": blind,
            "anchor_label": card["anchor_label"], "calibration": cal_used,
            "points": [{"label": p["label"], "value": p["value"], "measured": (measured or {}).get(p["label"]),
                        "pred": {v: preds[v].get(p["label"]) for v in preds}} for p in card["points"]],
            "scores": scores, "notes": notes}


# ---------------------------------------------------------------- generic optimiser
def objective(pred: dict, targets: dict) -> float:
    """Sum over targets of the miss in units of the target scale, plus a little band width."""
    tot = 0.0
    for q, t in targets.items():
        b = pred.get(q)
        if not b:
            return float("inf")
        v = b["value"]
        scale = abs(t.get("value") if t.get("value") is not None else (t.get("max") or t.get("min") or 1.0)) or 1.0
        miss = 0.0
        if t.get("value") is not None:
            miss = abs(v - t["value"])
        if t.get("max") is not None and v > t["max"]:
            miss += v - t["max"]
        if t.get("min") is not None and v < t["min"]:
            miss += t["min"] - v
        tot += miss / scale + 0.1 * (b["high"] - b["low"]) / scale
    return tot


def optimise(problem: dict, predictor: str, base: dict, n: int = 256, n_props: int = 3, seed: int = 0) -> dict:
    """Latin-hypercube search over the knobs, then the best diverse points refined locally."""
    from synthtwin.steps.case import explore
    knobs = {k: tuple(v) for k, v in problem["knobs"].items()}
    keys = list(knobs)
    fixed = dict(problem.get("fixed") or {})
    rng = np.random.default_rng(seed)
    d = len(keys)
    u = (np.argsort(rng.random((n, d)), axis=0) + rng.random((n, d))) / n
    lo = np.array([knobs[k][0] for k in keys])
    hi = np.array([knobs[k][1] for k in keys])

    def conds(x):
        return {**fixed, **{k: float(v) for k, v in zip(keys, lo + x * (hi - lo))}}
    res = explore._many(predictor, base, [conds(x) for x in u], 4, 4)
    sc = np.array([objective(r, problem["targets"]) for r in res])
    order = np.argsort(sc)
    picked: list[int] = []
    for i in order:
        if not np.isfinite(sc[i]):
            break
        if all(np.linalg.norm(u[i] - u[j]) > 0.2 for j in picked):
            picked.append(int(i))
        if len(picked) == n_props:
            break
    # local refinement around each pick
    props = []
    for k, i in enumerate(picked):
        local = np.clip(u[i] + rng.normal(0, 0.05, (24, d)), 0, 1)
        lr = explore._many(predictor, base, [conds(x) for x in local], 4, 4)
        ls = [objective(r, problem["targets"]) for r in lr]
        j = int(np.argmin(ls))
        x, r, s = (local[j], lr[j], ls[j]) if ls[j] < sc[i] else (u[i], res[i], sc[i])
        final = explore._many(predictor, base, [conds(x)], 16, 1)[0] or r
        props.append({"id": f"{problem.get('problem_id', 'p')}-{k + 1}", "method": problem.get("method", ""),
                      "conditions": conds(x), "score": float(s),
                      "predicted": {q: {**b} for q, b in final.items()},
                      "novelty": {}, "steps": [], "measurements": list(problem["targets"]),
                      "controls": [], "expected": "", "risks": []})
    best = [{"conditions": {k: conds(u[i])[k] for k in keys}, "why": "lower score", "score": float(sc[i])}
            for i in order[len(picked):len(picked) + 4] if np.isfinite(sc[i])]
    return {"proposals": props, "dropped": best, "novelty_check": "none (agent-built system)",
            "n_candidates": int(np.isfinite(sc).sum())}
