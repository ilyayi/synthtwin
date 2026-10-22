"""Benchmark the selected simulation stack on related studies before it is
trusted with the user's case.

Each study is a one-factor sweep: points with conditions, one anchor point
whose outcomes calibrate the model, the rest predicted and scored (MAE,
Spearman, trend, band coverage) with synthtwin.lib.sweep.score_sweep. Benchmark
cases are scored against their sealed vault (blind); web/library studies
against the numbers they report (not blind, labelled so).

Variants (each only if the stack allows it):
    null          every point = the anchor's outcomes (the floor to beat)
    uncalibrated  continuum model, published defaults
    calibrated    + 1-2 rate scales fitted on the anchor
    atomistic     + MD/DFT physics (surface energy, coalescence, capping)
"""
from __future__ import annotations

import importlib
import json
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

VARIANTS = {
    "null": "anchor value everywhere (floor)",
    "uncalibrated": "continuum model, defaults",
    "calibrated": "continuum + calibration on the anchor",
    "atomistic": "continuum + calibration + MD/DFT physics",
    "model": "agent-built model as built (other systems)",
}


def variants_for(stack: list[str]) -> list[str]:
    out = ["null"]
    if "continuum" in stack:
        out.append("uncalibrated")
        if "calibration" in stack:
            out.append("calibrated")
        if {"md_eam", "dft_lit"} & set(stack):
            out.append("atomistic")
    return out


def study_to_case(study: dict, quantities: list[str]) -> tuple[dict, dict] | None:
    """A web/library study with reported outcomes -> (card dict, {label: {q: v}})."""
    pts = [p for p in study["points"] if p.get("outcomes")]
    qs = [q for q in quantities if sum(q in (p["outcomes"] or {}) for p in pts) >= 3]
    if not qs or not study.get("swept"):
        return None
    key = study["swept"][0]["key"]
    pts = [p for p in pts if all(q in p["outcomes"] for q in qs)]
    if len(pts) < 3:
        return None
    for i, p in enumerate(pts):
        if p.get("value") is None:
            p = {**p, "value": (p.get("conditions") or {}).get(key, i)}
            pts[i] = p
    ordered = sorted(pts, key=lambda p: (float(p["value"]), str(p["label"])))
    anchor = ordered[(len(ordered) - 1) // 2]
    card = {"case_id": study["id"], "paper_title": study["title"], "paper_url": study.get("url", ""),
            "licence": "", "published": str(study.get("year", "")), "post_cutoff": False,
            "material": study.get("material", ""), "method": study.get("method", ""),
            "sweep_variable": key, "quantities": qs,
            "points": [{"label": p["label"], "value": p["value"], "conditions": p.get("conditions") or {},
                        "reagents": []} for p in pts],
            "anchor_label": anchor["label"],
            "anchor_outcomes": [{"quantity": q, "value": anchor["outcomes"][q], "unit": ""} for q in qs]}
    return card, {p["label"]: {q: p["outcomes"][q] for q in qs} for p in pts}


def _vault(vault_dir: Path | None, case_id: str) -> dict | None:
    if not vault_dir:
        return None
    f = Path(vault_dir) / f"{case_id}.json"
    if not f.is_file():
        return None
    v = json.loads(f.read_text())
    return {label: {o["quantity"]: o["value"] for o in outs} for label, outs in v["outcomes"].items()}


def _physics(params: dict) -> dict | None:
    try:
        from synthtwin.lib.atomistic.params import physics_overrides
    except ImportError:
        return None
    capping = next((r["name"] for r in params.get("reagents", []) if r.get("role") == "capping"), "citrate")
    cap = "tannic" if "tannic" in capping.lower() else "citrate"
    try:
        return {k: v for k, v in physics_overrides(params["material"], cap).items()
                if not k.startswith("_") and isinstance(v, (int, float))}
    except Exception:
        return None


def run_case(card: dict, measured: dict | None, variants: list[str], predictor: str = "synthtwin.lib.np.model",
             n_draws: int = 16, blind: bool = True) -> dict:
    """-> {case_id, points: [{label, value, measured, pred: {variant: {q: band}}}], scores, notes}."""
    from synthtwin.lib.np import cases
    from synthtwin.core.schemas import Outcome, SweepCase, SweepPrediction, SweepVault
    from synthtwin.lib.sweep import null_predict, score_sweep
    M = importlib.import_module(predictor)
    case = SweepCase.model_validate(card)
    anchor = next(p for p in card["points"] if p["label"] == card["anchor_label"])
    anchor_out = {o["quantity"]: o["value"] for o in card["anchor_outcomes"]}
    preds: dict[str, dict[str, dict]] = {}
    notes, cal_used = [], {}
    _, how = cases.recipe(card, anchor)
    notes.append(f"recipe translation: {how}")
    for var in variants:
        if var == "null":
            preds["null"] = {lbl: {q: b.model_dump() for q, b in bands.items()}
                             for lbl, bands in null_predict(case).points.items()}
            continue
        phys = _physics(cases.recipe(card, anchor)[0]) if var == "atomistic" else None
        if var == "atomistic" and not phys:
            notes.append("atomistic: no MD/DFT values for this material")
            continue
        cal: dict = {}
        if var in ("calibrated", "atomistic") and hasattr(M, "calibrate"):
            seed = _seed(card, M, {}, phys)
            ap = cases.recipe(card, anchor, seed)[0]
            cal = M.calibrate({**ap, "physics": phys}, [Outcome(**o) for o in card["anchor_outcomes"]]) or {}
            cal_used[var] = cal
        seed = _seed(card, M, cal, phys)
        out = {}
        for p in card["points"]:
            prm = cases.recipe(card, p, seed)[0]
            prm.update(calibration={**(prm.get("calibration") or {}), **cal}, physics=phys, n_draws=n_draws)
            try:
                res = M.predict(prm)
            except Exception as exc:
                notes.append(f"{var} {p['label']}: {type(exc).__name__}")
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
    else:
        notes.append("no measured values available here: predictions only, not scored")
    return {"case_id": card["case_id"], "title": card.get("paper_title", ""), "url": card.get("paper_url", ""),
            "sweep_variable": card["sweep_variable"], "quantities": card["quantities"], "blind": blind,
            "anchor_label": card["anchor_label"], "calibration": cal_used,
            "points": [{"label": p["label"], "value": p["value"], "measured": (measured or {}).get(p["label"]),
                        "pred": {v: preds[v].get(p["label"]) for v in preds}} for p in card["points"]],
            "scores": scores, "notes": notes}


def _seed(card: dict, M: Any, cal: dict, phys: dict | None) -> tuple[float, float] | None:
    from synthtwin.lib.np import cases
    fn = cases.NEEDS_SEED.get(card["case_id"])
    if not fn:
        return None
    r = M.predict({**fn(), "calibration": cal, "physics": phys})
    return r["size_mean_nm"]["value"], r.get("size_cv_pct", {"value": 10.0})["value"]


def verdict(case: dict) -> dict:
    """Per variant, on the primary quantity: does it get the trend and beat null?"""
    q = case["quantities"][0]
    by = {s["variant"]: s for s in case["scores"] if s["quantity"] == q}
    null = by.get("null")
    out = {}
    for var, s in by.items():
        if var == "null":
            continue
        ok = bool(s["trend_ok"] and null and s["mae"] < null["mae"])
        out[var] = {"validated": ok, "mae": s["mae"], "null_mae": null and null["mae"],
                    "spearman": s["spearman"], "trend_ok": s["trend_ok"]}
    return out


def run(jobs: list[tuple[dict, dict | None, bool]], variants: list[str], predictor: str = "synthtwin.lib.np.model",
        workers: int = 4, n_draws: int = 16) -> list[dict]:
    """jobs: (card, measured, blind). Cases run in parallel processes."""
    if workers <= 1 or len(jobs) <= 1:
        return [run_case(c, m, variants, predictor, n_draws, b) for c, m, b in jobs]
    with ProcessPoolExecutor(max_workers=min(workers, len(jobs)), mp_context=mp.get_context("spawn")) as ex:
        futs = [ex.submit(run_case, c, m, variants, predictor, n_draws, b) for c, m, b in jobs]
        out = []
        for f, (c, _, b) in zip(futs, jobs):
            try:
                out.append(f.result())
            except Exception as exc:
                out.append({"case_id": c["case_id"], "title": c.get("paper_title", ""), "error": f"{type(exc).__name__}: {exc}",
                            "points": [], "scores": [], "quantities": c["quantities"], "blind": b, "notes": []})
        return out


def jobs_for(sample: list[dict], cards: dict[str, dict], vault_dir: Path | None, targets: list[str]) -> list:
    jobs = []
    for s in sample:
        if s["source"] == "benchmark":
            card = cards[s["case_id"]]
            jobs.append((card, _vault(vault_dir, card["case_id"]), True))
        else:
            got = study_to_case(s, targets or ["size_mean_nm"])
            if got:
                jobs.append((got[0], got[1], False))
    return jobs
