"""The bench step's handlers: apply (the variant verdict), work (the phase's
background job: build the simulator for other systems, then predict the sample
and score it blind) and confirm (the gate into case)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from synthtwin import steps
from synthtwin.core import catalog, systems
from synthtwin.steps.bench import bench as benchmod
from synthtwin.steps.bench import builder


def apply(agent, s: dict, ans: dict) -> Callable | None:
    """The agent's highlighted variant, if it is one this benchmark ran."""
    if ans.get("variant") in (s["phases"]["bench"].get("variants") or []):
        s["phases"]["bench"]["variant"] = ans["variant"]
    return None


def workdir(agent, sid: str) -> Path:
    """The study's build folder (model.py, NOTES.md, QA.md live there)."""
    return agent.cfg.data_dir / "systems" / sid


def build(agent, sid: str) -> dict:
    """Other systems: a builder agent runs the approved stack and writes model.py (benchmark studies held out)."""
    s = agent.load(sid)
    pb = s["problem"]
    chosen = {c["id"] for c in s["phases"]["sample"].get("candidates", []) if c.get("selected")}
    bm = agent.cfg.build_minutes
    agent._busy(sid, "building and running the simulations, then QA review ("
                + (f"up to {bm} min" if bm else "no time limit; progress in the Benchmark panel") + ")")
    if (workdir(agent, sid) / "NOTES.md").exists():
        msg = ("Resuming the simulator build after a server restart: its jobs kept running and the builder "
               "picks up from its notes.")
    elif chosen:
        msg = ("Building the simulator now: the builder runs the approved stack on this machine and "
               "assembles a predictor. It never sees the outcomes of the studies you picked for the "
               "benchmark, only one anchor point each, so the test that follows is blind.")
    else:
        msg = ("Building the simulator now: the builder runs the approved stack on this machine and "
               "assembles a predictor. With no benchmark studies, its predictions stay exploratory.")
    agent.mutate(sid, lambda s: s["chat"].append({"role": "agent", "phase": "bench", "at": time.time(), "text": msg}))
    out = builder.build(agent.cfg.llm, workdir(agent, sid), {**pb, "problem_id": sid},
                        s["phases"]["stack"].get("methods", []), s["phases"]["prior"].get("studies", []),
                        chosen, agent.cfg.tools, bm, agent.cfg.qa_rounds,
                        progress=lambda p: agent.mutate(sid, lambda s: s["phases"]["bench"].update(progress=p)),
                        toolbox=agent.cfg.toolbox, chain=s["phases"]["stack"].get("chain"))
    agent.mutate(sid, lambda s: (s["phases"]["bench"].update(build=out), s["phases"]["bench"].pop("progress", None)))
    if not out["check"]["ok"]:
        raise RuntimeError("the built model fails its contract check: " + out["check"]["out"][-300:])
    return out


def work(agent, sid: str) -> None:
    """The phase's background job: predict every sample study, score each variant
    against the sealed outcomes, pick the best variant, then the agent's turn."""
    s = agent.load(sid)
    pb = s["problem"]
    generic = not systems.is_builtin(pb)
    stack = [m["id"] for m in s["phases"]["stack"]["methods"] if m["selected"]]
    variants = ["null", "model", "calibrated"] if generic else benchmod.variants_for(stack)
    chosen = {c["id"] for c in s["phases"]["sample"]["candidates"] if c.get("selected")}
    studies = [x for x in s["phases"]["prior"]["studies"] if x["id"] in chosen]
    jobs = benchmod.jobs_for(studies, agent.cards(), agent.cfg.vault, list(pb["targets"]))
    module = agent.cfg.predictor or "synthtwin.lib.np.model"
    if generic:
        b = s["phases"]["bench"].get("build")
        if not (b and b["check"]["ok"] and Path(b["path"]).is_file()):
            b = build(agent, sid)
        module = "file:" + b["path"]
        agent._busy(sid, "benchmarking the built model on the held-out studies")
    t0 = time.time()
    if generic:
        cases = []
        for card, measured, blind in jobs:
            try:
                cases.append(systems.run_case(card, measured, module, pb.get("fixed") or {}, blind))
            except Exception as exc:
                cases.append({"case_id": card["case_id"], "title": card.get("paper_title", ""), "scores": [],
                              "error": f"{type(exc).__name__}: {exc}", "points": [],
                              "quantities": card["quantities"], "blind": blind, "notes": []})
    elif pb["material"] not in catalog.NP_MATERIALS and not agent.cfg.predictor:
        cases = []
    else:
        cases = benchmod.run(jobs, variants, module, workers=agent.cfg.workers)
    if generic and not any(c.get("calibration", {}).get("calibrated") is not None for c in cases):
        variants = [v for v in variants if v != "calibrated"]
    table, wins = [], {v: 0 for v in variants if v != "null"}
    ratio = {v: [] for v in wins}
    for c in cases:
        v = benchmod.verdict(c) if c.get("scores") else {}
        c["verdict"] = v
        for var, x in v.items():
            wins[var] += x["validated"]
            if x["null_mae"]:
                ratio[var].append(x["mae"] / x["null_mae"])
        table.append({"case": c["case_id"], "title": c.get("title", "")[:80], "blind": c.get("blind"),
                      "quantity": c["quantities"][0] if c.get("quantities") else "",
                      "swept": c.get("sweep_variable"), "error": c.get("error"),
                      **{var: {"mae": round(x["mae"], 2), "null_mae": round(x["null_mae"] or 0, 2),
                               "spearman": None if x["spearman"] is None else round(x["spearman"], 2),
                               "validated": x["validated"]} for var, x in v.items()}})
    scored = [c for c in cases if c.get("scores")]
    best = None
    if wins:
        best = max(wins, key=lambda v: (wins[v], -(sum(ratio[v]) / len(ratio[v]) if ratio[v] else 9)))
    mean_ratio = {v: round(sum(r) / len(r), 2) if r else None for v, r in ratio.items()}
    # trusted: validated on at least half the studies AND better than the null floor on average
    trusted = bool(best and wins[best] and wins[best] >= len(scored) / 2
                   and mean_ratio.get(best) is not None and mean_ratio[best] < 1.0)
    summary = {"n_cases": len(cases), "n_scored": len(scored), "variants": list(wins),
               "validated": wins, "mean_mae_over_null": mean_ratio,
               "best": best, "trusted": trusted,
               "seconds": round(time.time() - t0, 1)}

    def put(s):
        s["phases"]["bench"].update(cases=cases, table=table, summary=summary, variants=list(wins),
                                    variant=best, status="awaiting_user")
    agent.mutate(sid, put)
    agent.turn(sid)


def confirm(agent, sid: str, s: dict, body: dict) -> None:
    """The gate: the researcher's chosen variant wins; the case simulation starts."""
    if body.get("variant") in (s["phases"]["bench"].get("variants") or []):
        agent.mutate(sid, lambda x: x["phases"]["bench"].update(variant=body["variant"]))
    agent.mutate(sid, lambda s: agent._advance(s, "case"))
    agent.background(sid, "simulating your case (about 1-2 min)", lambda: steps.run("case").work(agent, sid))
