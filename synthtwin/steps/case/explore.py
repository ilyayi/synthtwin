"""Study the user's case with the trusted stack: one-knob sweeps with bands, a
2-D map over the two most influential knobs, a sensitivity tornado, the
optimiser's recipes, and the predicted spectrum/size histogram of the best one.
Everything returned is plain JSON for the charts.
"""
from __future__ import annotations

import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
from typing import Any

import numpy as np


class Bound:
    """A predictor with the study's calibration, physics and draw count baked in
    (optimize.run only passes material/method/conditions)."""

    def __init__(self, module: str, base: dict, n_draws: int = 8):
        self.module, self.base, self.n_draws = module, base, n_draws
        from synthtwin.core import systems
        self.M = systems.load(module)
        self.built = module.startswith("file:")

    def params(self, conditions: dict, n_draws: int | None = None) -> dict:
        return {"material": self.base["material"], "method": self.base.get("method", ""),
                "conditions": dict(conditions), "reagents": self.base.get("reagents", []),
                "calibration": self.base.get("calibration") or None, "physics": self.base.get("physics"),
                "n_draws": n_draws or self.n_draws}

    def predict(self, params: dict) -> dict:
        cond = params.get("conditions") or {}
        if self.built:
            from synthtwin.core import systems
            return systems.predict(self.M, self.params(cond, params.get("n_draws")))
        return self.M.predict(self.params(cond, params.get("n_draws")))


def _eval(module: str, base: dict, conds: list[dict], n_draws: int) -> list[dict]:
    b = Bound(module, base, n_draws)
    out = []
    for c in conds:
        try:
            out.append(b.predict({"conditions": c}))
        except Exception:
            out.append({})
    return out


def _many(module: str, base: dict, conds: list[dict], n_draws: int, workers: int) -> list[dict]:
    if workers <= 1 or len(conds) < 8:
        return _eval(module, base, conds, n_draws)
    chunks = [conds[i::workers] for i in range(workers)]
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex:
        parts = list(ex.map(_eval, [module] * workers, [base] * workers, chunks, [n_draws] * workers))
    out: list[dict] = [{}] * len(conds)
    for i, part in enumerate(parts):
        for j, r in enumerate(part):
            out[i + j * workers] = r
    return out


def _band(r: dict, q: str) -> dict | None:
    b = r.get(q)
    return None if not b else {"value": b["value"], "low": max(b["low"], 0.0), "high": b["high"]}


def explore(problem: dict, module: str, base: dict, workers: int = 6, n_sweep: int = 13, n_grid: int = 12) -> dict:
    """problem: {targets: {q: {value|min|max}}, knobs: {k: [lo, hi]}, fixed: {k: v}}."""
    knobs = {k: tuple(v) for k, v in problem["knobs"].items()}
    fixed = dict(problem.get("fixed") or {})
    targets = problem["targets"]
    primary = next(iter(targets))
    mid = {**fixed, **{k: (lo + hi) / 2 for k, (lo, hi) in knobs.items()}}
    qs = list(dict.fromkeys(list(targets) + ([] if module.startswith("file:") else ["size_mean_nm"])))

    # 1-D sweeps (all knobs in one batch)
    conds, idx = [], []
    for k, (lo, hi) in knobs.items():
        for x in np.linspace(lo, hi, n_sweep):
            conds.append({**mid, k: float(x)})
            idx.append(k)
    res = _many(module, base, conds, 8, workers)
    sweeps = {k: {"x": [], **{q: [] for q in qs}} for k in knobs}
    for k, c, r in zip(idx, conds, res):
        sweeps[k]["x"].append(c[k])
        for q in qs:
            sweeps[k][q].append(_band(r, q))

    # tornado: swing of the primary quantity across each knob's range
    tornado = []
    for k in knobs:
        vals = [b["value"] for b in sweeps[k][primary] if b]
        if vals:
            tornado.append({"knob": k, "low": vals[0], "high": vals[-1], "min": min(vals), "max": max(vals),
                            "swing": max(vals) - min(vals)})
    tornado.sort(key=lambda t: -t["swing"])
    center = _band(_eval(module, base, [mid], 8)[0], primary)

    # 2-D map over the two knobs that move the primary quantity most
    heat = None
    if len(knobs) >= 2:
        kx, ky = tornado[0]["knob"], tornado[1]["knob"]
        xs = np.linspace(*knobs[kx], n_grid)
        ys = np.linspace(*knobs[ky], n_grid)
        grid = [{**mid, kx: float(x), ky: float(y)} for y in ys for x in xs]
        gres = _many(module, base, grid, 1, workers)
        z = [[(gres[j * n_grid + i].get(primary) or {}).get("value") for i in range(n_grid)] for j in range(n_grid)]
        heat = {"x_key": kx, "y_key": ky, "x": xs.tolist(), "y": ys.tolist(), "z": z, "quantity": primary,
                "target": targets[primary]}
    return {"primary": primary, "mid": mid, "center": center, "sweeps": sweeps, "tornado": tornado,
            "heatmap": heat, "quantities": qs}


def spectrum(module: str, base: dict, conditions: dict) -> dict | None:
    b = Bound(module, base, 16)
    if not hasattr(b.M, "spectrum"):
        return None
    s = b.M.spectrum(b.params(conditions, 16))
    keep = ("wavelength_nm", "absorbance", "absorbance_low", "absorbance_high", "lspr_nm", "lspr_fwhm_nm",
            "d_centers_nm", "number_per_m3", "time_course")
    out = {k: s[k] for k in keep if k in s}
    return out


def optimise(problem_d: dict, module: str, base: dict, robot_path: str, library: list, n_eval: int = 30) -> dict:
    """Optimiser + novelty + robot feasibility -> candidates and proposals (plain dicts)."""
    import yaml

    from synthtwin.lib.design import calibrate as calmod
    from synthtwin.lib.design import optimize, propose
    from synthtwin.lib.design import run as drun
    from synthtwin.lib.design.problem import validate
    from synthtwin.core.schemas import Problem, RobotProfile

    problem = validate(Problem(**problem_d))
    pred = Bound(module, base, 4)
    cal = calmod.Calibration(params=base.get("calibration") or {}, status="calibrated" if base.get("calibration") else "uncalibrated",
                             band_factor=1.0 if base.get("calibration") else calmod.UNCALIBRATED_BAND_FACTOR)
    cands = optimize.run(problem, pred, cal, n_eval=n_eval)
    robot = RobotProfile(**yaml.safe_load(open(robot_path).read()))
    check, used = drun.novelty_fn()
    if used.startswith("synthtwin.lib.recipes"):
        _check = check

        def check(cand, lib):
            return _check({"recipe_id": "candidate", "source": "manual", "material": problem.material,
                           "method": cand.method, "reagents": cand.reagents, "conditions": cand.conditions}, lib)
    _strict = check

    def check(cand, lib):   # thin coverage means unmapped, not known: keep it (propose.risks flags it)
        nov = _strict(cand, lib)
        return nov.model_copy(update={"novel": True}) if nov.coverage == "thin" else nov
    props = propose.make(problem, cands, check, robot, library)
    kept = {id(p.candidate) for p in props}
    stocks, names = propose.parse_stocks(robot), propose.family_reagent_names(library, problem)
    dropped = []
    for c in cands:
        if id(c) in kept or len(dropped) >= 8:
            continue
        nov = check(c, library)
        why = (f"repeats known work: {nov.reason or nov.nearest_recipe_id}" if not nov.novel
               else "; ".join(propose.feasibility(c, robot, stocks, names).reasons) or "lower score")
        dropped.append({"conditions": {k: c.conditions[k] for k in problem.knobs}, "why": why, "score": c.score})
    out = []
    for p in props:
        c = p.candidate
        out.append({"id": p.proposal_id, "method": c.method, "conditions": c.conditions, "score": c.score,
                    "predicted": {q: {"value": b.value, "low": max(b.low, 0.0), "high": b.high, "unit": b.unit}
                                  for q, b in c.predicted.items()},
                    "novelty": p.novelty.model_dump(), "steps": p.steps, "measurements": p.measurements,
                    "controls": p.controls, "expected": p.expected, "risks": p.risks})
    return {"proposals": out, "dropped": dropped, "novelty_check": used, "n_candidates": len(cands)}
