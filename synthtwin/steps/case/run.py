"""The case step's handlers: apply (the agent's insights and new knob ranges),
work (the phase's background job: sweeps, the 2-D map, the tornado, the
optimiser's proposals, the spectrum) and confirm (the gate into recipe)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from synthtwin.core import catalog, systems
from synthtwin.steps.bench import bench as benchmod
from synthtwin.steps.case import explore


def apply(agent, s: dict, ans: dict) -> Callable | None:
    """The insights are recorded; new knob ranges only when the researcher asked."""
    P = s["phases"]["case"]
    if ans.get("insights"):
        P["insights"] = ans["insights"]
    if ans.get("knobs") and s["chat"][-1]["role"] == "user":   # only when the researcher asked
        kn = {k["key"]: [float(k["lo"]), float(k["hi"])] for k in ans["knobs"] if k["lo"] < k["hi"]}
        if kn:
            s["problem"]["knobs"].update(kn)
            sid = s["id"]
            return lambda: (agent._busy(sid, "re-running your case"), work(agent, sid))
    return None


def basis(agent, s: dict) -> dict:
    """Calibration/physics for the user's case, from the benchmark's chosen variant."""
    pb = s["problem"]
    B = s["phases"]["bench"]
    generic = not systems.is_builtin(pb)
    var = B.get("variant") or ("model" if generic else "uncalibrated" if pb["material"] in catalog.NP_MATERIALS
                               else None)
    base = {"material": pb["material"], "method": pb.get("method", ""), "reagents": []}
    why = [f"variant: {var or 'none'} ({benchmod.VARIANTS.get(var, '')})"]
    if var in ("calibrated", "atomistic"):
        meth = (pb.get("method") or "").lower()
        best = None
        for c in B.get("cases", []):
            cal = (c.get("calibration") or {}).get(var)
            if not cal:
                continue
            same = meth and meth.split()[0] in (next((x["method"] for x in s["phases"]["prior"]["studies"]
                                                       if x["id"] in (c["case_id"], f"case:{c['case_id']}")), "") or "").lower()
            ok = (c.get("verdict") or {}).get(var, {}).get("validated", False)
            key = (ok, bool(same))
            if best is None or key > best[0]:
                best = (key, c, cal)
        if best:
            base["calibration"] = best[2]
            why.append(f"calibration from {best[1]['case_id']} ({'validated' if best[0][0] else 'not validated'} there)")
    if var == "atomistic" and not generic:
        cap = "tannic" if "tannic" in (pb.get("method") or "").lower() else "citrate"
        base["physics"] = benchmod._physics({"material": pb["material"],
                                             "reagents": [{"role": "capping", "name": cap}]})
        why.append("physics: MD/DFT surface energy, coalescence and capping values")
    trusted = bool(B.get("summary", {}).get("trusted"))
    return {"base": base, "variant": var, "why": why, "label": "validated" if trusted else "exploratory"}


def work(agent, sid: str) -> None:
    """The phase's background job: explore the case, propose, then the recipe turn
    follows directly from the case."""
    s = agent.load(sid)
    pb = s["problem"]
    module = agent.cfg.predictor or "synthtwin.lib.np.model"
    if not systems.is_builtin(pb):
        _generic(agent, sid, s)
        return
    if pb["material"] not in catalog.NP_MATERIALS and not agent.cfg.predictor:
        agent.mutate(sid, lambda s: s["phases"]["case"].update(status="awaiting_user", unsupported=True))
        agent.turn(sid, f"No runnable simulator for {pb['material']}; explain what would be needed.")
        return
    b = basis(agent, s)
    t0 = time.time()
    ex = explore.explore(pb, module, b["base"], workers=agent.cfg.workers)
    heat = ex.get("heatmap")
    hs = None
    if heat:
        vals = [v for row in heat["z"] for v in row if v is not None]
        hs = {"x": heat["x_key"], "y": heat["y_key"], "quantity": heat["quantity"],
              "min": min(vals) if vals else None, "max": max(vals) if vals else None}
    agent.mutate(sid, lambda s: s["phases"]["case"].update(**ex, heat_summary=hs, basis=b))
    problem_d = {"problem_id": sid, "text": pb["text"], "material": pb["material"],
                 "methods": [pb["method"]] if pb.get("method") else [],
                 "targets": pb["targets"], "knobs": pb["knobs"], "fixed": pb["fixed"]}
    opt = explore.optimise(problem_d, module, b["base"], str(agent.cfg.robot), agent.library(),
                           n_eval=agent.cfg.n_eval)
    for p in opt["proposals"]:
        p["label"] = b["label"]
    spec = explore.spectrum(module, b["base"], opt["proposals"][0]["conditions"]) if opt["proposals"] else None
    agent.mutate(sid, lambda s: s["phases"]["case"].update(**opt, spectrum=spec, seconds=round(time.time() - t0, 1),
                                                            status="done"))
    agent.turn(sid)
    # the recipe follows directly from the case
    agent.mutate(sid, lambda s: agent._advance(s, "recipe"))
    agent.mutate(sid, lambda s: s["phases"]["recipe"].update(status="awaiting_user"))
    agent._busy(sid, "writing the recipe")
    agent.turn(sid)


def _generic(agent, sid: str, s: dict) -> None:
    """Any other system: the built model is the predictor; no spectrum to predict."""
    pb = s["problem"]
    b = s["phases"]["bench"].get("build") or {}
    if not (b.get("check", {}).get("ok") and Path(b.get("path", "")).is_file()):
        raise RuntimeError("no working model was built for this system; retry the benchmark phase")
    module = "file:" + b["path"]
    base = basis(agent, s)
    t0 = time.time()
    ex = explore.explore(pb, module, base["base"], workers=agent.cfg.workers)
    heat = ex.get("heatmap")
    hs = None
    if heat:
        vals = [v for row in heat["z"] for v in row if v is not None]
        hs = {"x": heat["x_key"], "y": heat["y_key"], "quantity": heat["quantity"],
              "min": min(vals) if vals else None, "max": max(vals) if vals else None}
    agent.mutate(sid, lambda s: s["phases"]["case"].update(**ex, heat_summary=hs, basis=base))
    opt = systems.optimise({**pb, "problem_id": sid}, module, base["base"])
    for p in opt["proposals"]:
        p["label"] = base["label"]
    agent.mutate(sid, lambda s: s["phases"]["case"].update(**opt, spectrum=None, seconds=round(time.time() - t0, 1),
                                                            status="done"))
    agent.turn(sid)
    agent.mutate(sid, lambda s: agent._advance(s, "recipe"))
    agent.mutate(sid, lambda s: s["phases"]["recipe"].update(status="awaiting_user"))
    agent._busy(sid, "writing the recipe")
    agent.turn(sid)


def confirm(agent, sid: str, s: dict, body: dict) -> None:
    """The gate: the case is read; the recipe turn starts."""
    agent.mutate(sid, lambda s: agent._advance(s, "recipe"))
    agent.background(sid, "writing the recipe", lambda: agent.turn(sid))
