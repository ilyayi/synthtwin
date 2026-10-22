"""The stack step's handlers: apply (the agent's chain, scales and method
ticks) and confirm (the gate into sample: the candidate studies the stack
could be benchmarked on)."""
from __future__ import annotations

import json
import re
import time
from typing import Callable

from synthtwin.steps.bench import bench as benchmod
from synthtwin.core import catalog, systems
from synthtwin.steps.stack.schema import clean_chain, clean_scales


def apply(agent, s: dict, ans: dict) -> Callable | None:
    """Store the chain and scales it designed, its method ticks, and the estimate."""
    P = s["phases"]["stack"]
    if isinstance(ans.get("chain"), list) and ans["chain"]:
        P["chain"] = clean_chain(ans["chain"])
    if isinstance(ans.get("scales"), list) and ans["scales"]:
        cleaned = clean_scales(ans["scales"], P.get("chain") or [], P.get("methods") or [])
        if cleaned:
            P["scales"] = cleaned
    if ans.get("methods") and not systems.is_builtin(s["problem"]):
        seen, ms = set(), []
        for m in ans["methods"]:
            mid = re.sub(r"[^a-z0-9_]+", "_", str(m.get("id", "")).lower()).strip("_")
            if mid and mid not in seen:
                seen.add(mid)
                ms.append({**m, "id": mid, "selected": bool(m.get("selected")), "status": "build",
                           "link": re.sub(r"[^a-z0-9_]+", "_", str(m.get("link", "")).lower()).strip("_")})
        if ms:
            P["methods"] = ms
        P["estimate"] = catalog.generic_estimate(P.get("methods", []))
    elif ans.get("methods"):
        by = {m["id"]: m for m in ans["methods"] if m.get("id") in catalog.BY_ID}
        for m in P.get("methods", []):
            if m["id"] in by:
                m["selected"] = bool(by[m["id"]]["selected"]) and catalog.available(
                    catalog.BY_ID[m["id"]], s["problem"].get("material", ""))
                m["insight"] = by[m["id"]].get("insight") or m["insight"]
        P["estimate"] = catalog.estimate([m["id"] for m in P.get("methods", []) if m["selected"]])
    return None


def confirm(agent, sid: str, s: dict, body: dict) -> None:
    """The gate: the researcher's own ticks win; the related studies that could
    benchmark the stack become the sample step's candidates."""
    if isinstance(body.get("selected"), list):   # the researcher's own ticks
        mat = s["problem"].get("material", "")

        def tick(x):
            for m in x["phases"]["stack"].get("methods", []):
                m["selected"] = m["id"] in body["selected"] and (
                    m["id"] not in catalog.BY_ID or catalog.available(catalog.BY_ID[m["id"]], mat))
            if not systems.is_builtin(x["problem"]):
                x["phases"]["stack"]["estimate"] = catalog.generic_estimate(x["phases"]["stack"]["methods"])
        agent.mutate(sid, tick)
        s = agent.load(sid)
    if not any(m["selected"] for m in s["phases"]["stack"].get("methods", [])):
        raise ValueError("select at least one method")
    pb = s["problem"]
    cards = agent.cards()
    cands = []
    for x in s["phases"]["prior"].get("studies", []):
        if x["source"] == "benchmark" and x["case_id"] in cards:
            n = len(x["points"])
        elif x["source"] != "benchmark" and benchmod.study_to_case(json.loads(json.dumps(x)), list(pb["targets"]) or ["size_mean_nm"]):
            n = sum(1 for p in x["points"] if p.get("outcomes"))
        else:
            continue
        cands.append({"id": x["id"], "source": x["source"], "title": x["title"], "url": x.get("url", ""),
                      "swept_key": (x["swept"] or [{"key": ""}])[0]["key"], "n_points": n, "blind": x["blind"],
                      "relevance": x["relevance"], "material": x["material"], "method": x["method"],
                      "selected": x["relevance"] >= 0.6})

    def go(s):
        agent._advance(s, "sample")
        s["phases"]["sample"].update(candidates=cands, status="awaiting_user")
    agent.mutate(sid, go)
    if not cands:
        agent.mutate(sid, lambda s: s["chat"].append({"role": "agent", "phase": "sample", "at": time.time(),
                    "text": "No related study has enough data points to benchmark on. You can go back to the "
                            "literature search, or skip the benchmark and run your case as exploratory."}))
        return
    agent.background(sid, "picking the benchmark sample", lambda: agent.turn(sid))
