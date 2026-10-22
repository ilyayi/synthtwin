"""Run one study through the pipeline (A1-A8), stage by stage, for the UI.

Each stage writes its status, a one-line summary, the decisions it took (with
the reason) and any tables into the study record, so the study page can show
how the run flowed. The steps are the same as synthtwin.lib.design.run; this module
only splits them into stages and records what happened. Vaults are never read:
A3 lists card metadata, A5 reads score files written by `sweep score`.
"""
from __future__ import annotations

import importlib
import json
import os
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import yaml

from synthtwin.ui.stages import STAGES

# A4: plausible range of each physics parameter (low, high) and what it is
PHYSICS_RANGES: dict[str, tuple[float, float, str]] = {
    "gamma_J_m2": (0.15, 0.60, "effective metal/solution surface energy (ripening, critical nucleus)"),
    "coalescence_dmax_nm": (0.0, 5.0, "largest particle size that still coalesces (early growth, spread)"),
    "coalescence_eff": (0.005, 0.1, "collision efficiency of small clusters"),
    "capping_dG_eV": (-0.6, -0.2, "capping-agent binding free energy (growth slow-down, pH effects)"),
    "ligand_shell_nm": (0.5, 3.0, "ligand shell thickness seen by DLS"),
}
# A4.2 decision for each parameter when it is sensitive (decision order: literature, MD, DFT, ML)
PHYSICS_METHOD: dict[str, tuple[str, str]] = {
    "gamma_J_m2": ("literature DFT + classical MD",
                   "facet energies from DFT; EAM MD of 1.5-8 nm clusters gives the size trend slabs miss"),
    "coalescence_dmax_nm": ("classical MD", "EAM MD of particle pairs vs size and T; vacuum gives an upper bound"),
    "coalescence_eff": ("classical MD", "same pair runs; efficiency from sintering fraction"),
    "capping_dG_eV": ("literature DFT", "published adsorption energies exist; new ligand+water DFT would take days"),
    "ligand_shell_nm": ("literature", "measured shell thicknesses; too insensitive to justify simulation"),
}
SENSITIVE_FRACTION = 0.15
VALIDATION_PREDICTOR = "A"


class Config:
    def __init__(self, data_dir: str | Path, library: str | Path, robot: str | Path,
                 cards: str | Path | None = None, scores: str | Path | None = None,
                 n_eval: int = 60, predictor: str | None = None):
        self.predictor = predictor   # module name; overrides the per-material default (tests use a stub)
        self.data_dir = Path(data_dir)
        self.library = Path(library)
        self.robot = Path(robot)
        self.cards = Path(cards) if cards else None
        self.scores = Path(scores) if scores else None
        self.n_eval = n_eval
        (self.data_dir / "studies").mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------ records
def new_study(study_id: str, problem: dict, title: str = "") -> dict:
    return {
        "id": study_id, "kind": "study", "title": title or problem.get("text", "")[:80] or study_id,
        "created": time.time(), "status": "queued", "problem": problem,
        "stages": [{"id": s["id"], "status": "pending", "summary": "", "decisions": [],
                    "tables": [], "log": []} for s in STAGES],
    }


def save(path: Path, study: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(study, indent=1, default=str))
    os.replace(tmp, path)


class Recorder:
    """Thread-safe writer for one study file."""

    def __init__(self, path: Path, study: dict):
        self.path, self.study, self.lock = path, study, threading.Lock()

    def stage(self, sid: str) -> dict:
        return next(s for s in self.study["stages"] if s["id"] == sid)

    def update(self, sid: str | None = None, **fields: Any) -> None:
        with self.lock:
            target = self.stage(sid) if sid else self.study
            target.update(fields)
            save(self.path, self.study)

    def decide(self, sid: str, question: str, answer: str, why: str = "") -> None:
        with self.lock:
            self.stage(sid)["decisions"].append({"q": question, "a": answer, "why": why})
            save(self.path, self.study)

    def table(self, sid: str, title: str, columns: list[str], rows: list[list[Any]]) -> None:
        with self.lock:
            self.stage(sid)["tables"].append({"title": title, "columns": columns, "rows": rows})
            save(self.path, self.study)

    def log(self, sid: str, msg: str) -> None:
        with self.lock:
            self.stage(sid)["log"].append(msg)
            save(self.path, self.study)


# ------------------------------------------------------------------ stages
def run_study(path: Path, cfg: Config) -> None:
    study = json.loads(path.read_text())
    rec = Recorder(path, study)
    rec.update(status="running")
    ctx: dict[str, Any] = {}
    for fn in (a1_problem, a2_library, a3_benchmark, a4_simulator, a5_validation, a6_design, a7_approval):
        sid = fn.__name__[:2].upper()
        rec.update(sid, status="running", started=time.time())
        try:
            ok = fn(rec, cfg, ctx)
        except Exception as exc:  # a stage error stops the run, visibly
            rec.update(sid, status="failed", summary=f"{type(exc).__name__}: {exc}",
                       error=traceback.format_exc(limit=4))
            rec.update(status="failed")
            return
        st = rec.stage(sid)
        if st["status"] == "running":
            rec.update(sid, status="done", finished=time.time())
        if ok is False:
            rec.update(status="failed")
            return
    rec.update(status="awaiting_user" if rec.study.get("proposals") else "complete")


DEFAULT_FIXED = {"total_volume_ml": 20.0, "conc_precursor_mM": 0.25}


def a1_problem(rec: Recorder, cfg: Config, ctx: dict) -> bool:
    from synthtwin.lib.design.problem import validate
    from synthtwin.core.schemas import Problem
    raw = dict(rec.study["problem"])
    raw.setdefault("problem_id", rec.study["id"])
    raw.setdefault("text", "")
    # the robot needs a volume and the model a precursor concentration; fill unset ones and say so
    raw["fixed"] = dict(raw.get("fixed") or {})
    assumed = {k: v for k, v in DEFAULT_FIXED.items() if k not in raw["fixed"] and k not in (raw.get("knobs") or {})}
    raw["fixed"].update(assumed)
    # knob ranges the robot cannot reach would only produce infeasible candidates
    robot = yaml.safe_load(cfg.robot.read_text()) if cfg.robot.is_file() else {}
    clipped = []
    for key, lim in (("temperature_C", robot.get("temperature_C")), ("total_volume_ml", robot.get("volume_ml"))):
        rng = (raw.get("knobs") or {}).get(key)
        if lim and rng and (rng[0] < lim[0] or rng[1] > lim[1]):
            new = [max(rng[0], lim[0]), min(rng[1], lim[1])]
            if new[0] < new[1]:
                raw["knobs"][key] = new
                clipped.append(f"{key} [{rng[0]:g}, {rng[1]:g}] -> [{new[0]:g}, {new[1]:g}]")
    try:
        problem = validate(Problem(**raw))
    except Exception as exc:
        rec.update("A1", status="failed", summary="Invalid problem; nothing else runs.")
        rec.decide("A1", "Is the problem valid?", "no", str(exc))
        return False
    ctx["problem"] = problem
    tg = ", ".join(f"{q} {_target(t)}" for q, t in problem.targets.items())
    rec.update("A1", summary=f"{problem.material}, {len(problem.knobs)} knobs; targets: {tg}")
    rec.decide("A1", "Are all targets measurable on the robot?", "yes",
               "every target is a known quantity: " + ", ".join(problem.targets))
    rec.decide("A1", "Are all knobs canonical conditions keys?", "yes", ", ".join(
        f"{k} [{lo:g}, {hi:g}]" for k, (lo, hi) in problem.knobs.items()))
    if clipped:
        rec.decide("A1", "Knobs clipped to the robot", "; ".join(clipped), "the robot profile cannot run outside these limits")
    if assumed:
        rec.decide("A1", "Unset conditions", ", ".join(f"{k}={v:g}" for k, v in assumed.items()),
                   "assumed defaults (not knobs or fixed in the problem); set them in the problem to change")
    if problem.fixed:
        rec.decide("A1", "Fixed conditions", ", ".join(f"{k}={v:g}" for k, v in problem.fixed.items()))
    return True


def a2_library(rec: Recorder, cfg: Config, ctx: dict) -> None:
    from synthtwin.lib.design import run as drun
    problem = ctx["problem"]
    library = drun.load_library(cfg.library)
    fb = cfg.data_dir / "feedback.jsonl"
    robot_recipes = drun.load_library(fb) if fb.exists() else []
    if robot_recipes:
        library = library + robot_recipes
        rec.decide("A2", "Robot feedback in the library?", f"yes, {len(robot_recipes)} recipes",
                   "results recorded in A8 of earlier studies (the feedback loop)")
    family, used = drun.recipe_search(library, problem)
    fam = [r for r in family if r.material == problem.material]
    with_out = [r for r in fam if r.outcomes]
    ctx.update(library=library, family=family)
    thin = len(fam) < 3
    rec.update("A2", summary=f"{len(fam)} {problem.material} recipes in the family "
               f"({len(with_out)} with measured outcomes) out of {len(library)} in the library",
               status="warn" if thin else "running")
    rec.decide("A2", "Family coverage", "thin" if thin else "ok",
               "fewer than 3 family recipes: candidates are reported as thin, never novel" if thin
               else f"{len(fam)} recipes of {problem.material} / {', '.join(problem.methods) or 'any method'}")
    rec.decide("A2", "Can the library calibrate the simulator?",
               "yes" if with_out else "no",
               f"{len(with_out)} family recipes report outcomes" if with_out
               else "no family recipe reports an outcome: the design runs uncalibrated (bands x2.5)")
    rows = []
    for r in fam[:12]:
        cond = ", ".join(f"{k}={v:g}" for k, v in list(r.conditions.items())[:4])
        outs = ", ".join(f"{o.quantity}={o.value:g}" for o in r.outcomes[:2]) or "-"
        rows.append([r.recipe_id, r.method, cond, outs, (r.paper_title or r.source)[:70]])
    rec.table("A2", f"Top family recipes (search: {used})",
              ["recipe", "method", "conditions", "outcomes", "source"], rows)


def _cards(cfg: Config) -> list[dict]:
    if not cfg.cards or not cfg.cards.is_dir():
        return []
    out = []
    for f in sorted(cfg.cards.glob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def a3_benchmark(rec: Recorder, cfg: Config, ctx: dict) -> None:
    problem = ctx["problem"]
    cards = [c for c in _cards(cfg) if c.get("material") == problem.material]
    ctx["cards"] = cards
    if not cards:
        rec.update("A3", status="warn", summary=f"No gold cases for {problem.material}: "
                   "the simulator cannot be validated for this family")
        rec.decide("A3", "Gold cases available?", "no",
                   "add open one-factor sweeps (blinded extraction) to validate this family")
        return
    rows = [[c["case_id"], c.get("method", ""), c.get("sweep_variable", ""), len(c.get("points", [])),
             ", ".join(c.get("quantities", [])), c.get("licence", ""), c.get("anchor_label", "")]
            for c in cards]
    rec.table("A3", "Gold cases (cards only; held-out values stay in the vault)",
              ["case", "method", "swept", "points", "quantities", "licence", "anchor"], rows)
    methods = sorted({c.get("method", "") for c in cards})
    rec.update("A3", summary=f"{len(cards)} gold sweeps for {problem.material} "
               f"({sum(len(c.get('points', [])) for c in cards)} points; methods: {', '.join(methods)})")
    rec.decide("A3", "What does the predictor see?", "one anchor point per case",
               "the median point's outcomes; every other point is sealed")


def _mid(problem) -> dict:
    return {"material": problem.material, "method": problem.methods[0] if problem.methods else "",
            "conditions": {**problem.fixed, **{k: (lo + hi) / 2 for k, (lo, hi) in problem.knobs.items()}},
            "reagents": []}


def _predictor_for(material: str, override: str | None = None):
    if override:
        return importlib.import_module(override), override
    if material in ("Au", "Ag"):
        from synthtwin.lib.np import model
        return model, "synthtwin.lib.np.model"
    raise ValueError(f"no simulator for material {material!r} yet (available: Au, Ag)")


def a4_simulator(rec: Recorder, cfg: Config, ctx: dict) -> None:
    problem = ctx["problem"]
    predictor, name = _predictor_for(problem.material, cfg.predictor)
    ctx["predictor"] = predictor
    base_params = _mid(problem)
    t0 = time.time()
    base = predictor.predict(base_params)
    dt = time.time() - t0
    size0 = base["size_mean_nm"]["value"]
    rec.decide("A4", "Simulator tier", f"continuum model ({name})",
               f"{dt:.2f} s per prediction at the knob mid-point (budget < 3 s for the optimiser)")
    rec.log("A4", f"mid-point prediction: size {size0:.2f} nm "
                  f"[{base['size_mean_nm']['low']:.2f}, {base['size_mean_nm']['high']:.2f}]")
    atom = _atomistic(problem.material)
    rows, sensitive = [], []
    for pname, (lo, hi, what) in PHYSICS_RANGES.items():
        vals = []
        for v in (lo, hi):
            r = predictor.predict({**base_params, "physics": {pname: v}})
            vals.append(r["size_mean_nm"]["value"])
        frac = (max(vals) - min(vals)) / max(size0, 1e-9)
        is_sens = frac >= SENSITIVE_FRACTION
        method, why = PHYSICS_METHOD[pname]
        if is_sens:
            sensitive.append(pname)
            decision = method
        else:
            decision, why = "keep default", f"size moves only {100 * frac:.0f} % across the plausible range"
        used = atom.get(pname)
        rows.append([pname, what, f"{lo:g} to {hi:g}", f"{min(vals):.1f} to {max(vals):.1f} nm",
                     "yes" if is_sens else "no", decision,
                     "-" if used is None else f"{used:g}", why])
    rec.table("A4", f"A4.2 gate: size_mean_nm at the mid-point ({size0:.1f} nm) across each parameter's range",
              ["parameter", "role", "range", "size range", "sensitive", "method", "atomistic value", "why"], rows)
    rec.decide("A4", "Which parameters pass the MD/DFT gate?",
               ", ".join(sensitive) or "none",
               "sensitive (>= 15 % size change) and not separately constrained by one anchor per case")
    rec.decide("A4", "Reduction kinetics by atomistic simulation?", "no",
               "no reliable reactive potential; ab initio MD in water is far over budget; rates are calibrated")
    if atom:
        ctx["physics"] = atom
        rec.decide("A4", "Atomistic values available?", "yes", ", ".join(f"{k}={v:g}" for k, v in atom.items())
                   + " (used only via physics overrides; never fitted to gold)")
    else:
        rec.decide("A4", "Atomistic values available?", "not yet",
                   "running on continuum defaults; the ablation in A5 decides whether physics overrides help")
    rec.update("A4", summary=f"{name}: {len(sensitive)} of {len(PHYSICS_RANGES)} physics parameters "
               f"pass the MD/DFT gate ({', '.join(sensitive) or 'none'})")


def _atomistic(material: str) -> dict:
    try:
        from synthtwin.lib.atomistic.params import physics_overrides  # type: ignore
    except ImportError:
        return {}
    try:
        vals = physics_overrides(material, "citrate")
    except Exception:
        return {}
    return {k: v for k, v in vals.items() if not k.startswith("_") and isinstance(v, (int, float))}


def _scores(cfg: Config) -> list[dict]:
    if not cfg.scores or not cfg.scores.exists():
        return []
    files = [cfg.scores] if cfg.scores.is_file() else sorted(cfg.scores.glob("*scores.jsonl"))
    rows = []
    for f in files:
        for line in f.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def a5_validation(rec: Recorder, cfg: Config, ctx: dict) -> None:
    problem = ctx["problem"]
    cards = {c["case_id"]: c for c in ctx.get("cards", [])}
    fam_cases = [cid for cid, c in cards.items()
                 if not problem.methods or c.get("method") in problem.methods]
    scores = [s for s in _scores(cfg) if s["case_id"] in fam_cases]
    ctx["validated"] = None
    if not scores:
        rec.update("A5", status="warn", summary="No benchmark scores for this family: every candidate is exploratory")
        rec.decide("A5", "Is the family validated?", "no", "no scored gold cases for this material and method")
        return
    by = {(s["case_id"], s["quantity"], s["predictor"]): s for s in scores}
    preds = sorted({s["predictor"] for s in scores} - {"null"})
    main = VALIDATION_PREDICTOR if VALIDATION_PREDICTOR in preds else (preds[0] if preds else None)
    rows, wins = [], []
    for (cid, q, p), s in sorted(by.items()):
        if p != main or q != "size_mean_nm":
            continue
        null = by.get((cid, q, "null"))
        # a case counts as validated if any run of the model gets the trend and beats null
        good = [r for r in preds if (x := by.get((cid, q, r))) and null and x.get("trend_ok")
                and x["mae"] is not None and x["mae"] < null["mae"]]
        wins.append(bool(good))
        rows.append([cid, cards[cid].get("sweep_variable", ""), s["n_points"],
                     _f(null and null["mae"]), _f(s["mae"]), _f(s.get("spearman")),
                     "yes" if s.get("trend_ok") else "no",
                     f"validated ({', '.join(good)})" if good else "not validated"])
    rec.table("A5", f"size_mean_nm, predictor {main} vs null (per case)",
              ["case", "swept", "n", "null MAE", "model MAE", "Spearman", "trend_ok", "verdict"], rows)
    ab = [p for p in preds if p != main]
    if ab:
        arow = []
        for p in [main] + ab:
            sel = [s for s in scores if s["predictor"] == p and s["quantity"] == "size_mean_nm"]
            arow.append([p, len(sel), sum(bool(s.get("trend_ok")) for s in sel),
                         _f(sum(s["mae"] for s in sel) / len(sel)) if sel else "-"])
        rec.table("A5", "Ablation on the same cases (size_mean_nm)",
                  ["run", "cases", "trend_ok", "mean MAE"], arow)
    n_ok = sum(wins)
    validated = n_ok > 0 and n_ok >= len(wins) / 2
    ctx["validated"] = validated
    rec.decide("A5", "Is the family validated?", "yes" if validated else "no",
               f"{n_ok} of {len(wins)} cases get trend_ok and beat the null MAE (any run: {', '.join(preds)})")
    if not validated:
        rec.decide("A5", "Consequence", "candidates are labelled exploratory",
                   "a model revision after seeing these scores is post-hoc and must be tested on new blinded cases")
    rec.update("A5", status="running" if validated else "warn",
               summary=f"{n_ok}/{len(wins)} cases validated for predictor {main}: "
               + ("family validated" if validated else "family not validated, candidates exploratory"))


def _f(v: Any) -> str:
    return "-" if v is None else f"{v:.2f}"


def _target(t) -> str:
    if t.value is not None:
        return f"= {t.value:g}"
    return " ".join(x for x in (f">= {t.min:g}" if t.min is not None else "",
                                f"<= {t.max:g}" if t.max is not None else "") if x)


def a6_design(rec: Recorder, cfg: Config, ctx: dict) -> None:
    from synthtwin.lib.design import calibrate as calmod, optimize, propose
    from synthtwin.lib.design import run as drun
    from synthtwin.core.schemas import RobotProfile
    problem, predictor, library = ctx["problem"], ctx["predictor"], ctx["library"]
    robot = RobotProfile(**yaml.safe_load(cfg.robot.read_text()))
    cal = calmod.family(predictor, ctx["family"], problem)
    rec.decide("A6", "Calibration", cal.status,
               f"{cal.n} family recipes; params {json.dumps({k: round(v, 3) if isinstance(v, float) else v for k, v in cal.params.items()})}"
               + ("" if cal.status == "calibrated" else f"; bands widened x{cal.band_factor:g}"))
    methods = drun.resolve_method(problem, cal, library)
    if methods and methods != problem.methods:
        problem = problem.model_copy(update={"methods": methods})
    rec.log("A6", f"optimising {', '.join(problem.knobs)} ({cfg.n_eval} evaluations, method {problem.methods[0] if problem.methods else '?'})")
    t0 = time.time()
    cands = optimize.run(problem, predictor, cal, n_eval=cfg.n_eval)
    rec.log("A6", f"{len(cands)} candidates in {time.time() - t0:.0f} s")
    check, used = drun.novelty_fn()
    if used.startswith("synthtwin.lib.recipes"):
        _check = check

        def check(cand, lib):
            return _check({"recipe_id": "candidate", "source": "manual", "material": problem.material,
                           "method": cand.method, "reagents": cand.reagents,
                           "conditions": cand.conditions}, lib)
    props = propose.make(problem, cands, check, robot, library)
    rec.decide("A6", "Novelty check", used, f"{len(cands)} candidates -> {len(props)} novel, robot-feasible proposals")
    kept = {id(p.candidate) for p in props}
    stocks, names = propose.parse_stocks(robot), propose.family_reagent_names(library, problem)
    dropped = []
    for c in cands:
        if id(c) in kept or len(dropped) >= 10:
            continue
        nov = check(c, library)
        why = (f"repeats known work: {nov.reason or nov.nearest_recipe_id}" if not nov.novel
               else "; ".join(propose.feasibility(c, robot, stocks, names).reasons) or "beyond n_proposals")
        dropped.append([", ".join(f"{k}={c.conditions[k]:.3g}" for k in problem.knobs if k in c.conditions), why])
    if dropped:
        rec.table("A6", "Candidates not proposed", ["knobs", "why"], dropped)
    label = {True: "validated", False: "exploratory", None: "exploratory"}[ctx.get("validated")]
    out = []
    for p in props:
        c = p.candidate
        pred = {q: {"value": b.value, "low": max(b.low, 0.0), "high": b.high, "unit": b.unit}
                for q, b in c.predicted.items()}
        out.append({"id": p.proposal_id, "method": c.method,
                    "conditions": c.conditions, "predicted": pred, "score": c.score,
                    "label": label if ctx.get("validated") is not None else (
                        "validated range" if c.in_validated_region else "exploratory"),
                    "novelty": p.novelty.model_dump(), "steps": p.steps, "measurements": p.measurements,
                    "controls": p.controls, "expected": p.expected, "risks": p.risks,
                    "decision": None})
    rows = [[o["id"], ", ".join(f"{k}={o['conditions'][k]:.3g}" for k in problem.knobs if k in o["conditions"]),
             " | ".join(f"{q} {b['value']:.2f} [{b['low']:.2f}, {b['high']:.2f}]"
                        for q, b in o["predicted"].items() if q in problem.targets),
             o["novelty"]["coverage"], o["label"]] for o in out]
    rec.table("A6", "Proposals", ["proposal", "knobs", "predicted (target quantities)", "coverage", "label"], rows)
    rec.update(proposals=out)
    rec.update("A6", summary=f"{len(out)} proposals ({label}); calibration {cal.status}",
               status="running" if out else "warn")


def a7_approval(rec: Recorder, cfg: Config, ctx: dict) -> None:
    n = len(rec.study.get("proposals") or [])
    if not n:
        rec.update("A7", status="skipped", summary="Nothing to approve")
        return
    rec.update("A7", status="awaiting_user", summary=f"{n} proposals wait for a person to approve or reject")
