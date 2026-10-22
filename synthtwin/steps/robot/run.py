"""The robot step's handlers: package (the protocol package for the
self-building lab, written next to the request), fill (the agent lists the
materials and equipment when the recipe did not), and result (the researcher
enters what a run measured; it is compared with the prediction and fed back
into the library; every run is kept)."""
from __future__ import annotations

import json
import time

from synthtwin import steps
from synthtwin.steps.recipe.schema import EQUIPMENT, MATERIALS
from synthtwin.steps.robot import package as pkg

FILL = {"type": "object", "properties": {"materials": MATERIALS, "equipment": EQUIPMENT},
        "required": ["materials", "equipment"]}


def package(agent, s: dict, req: dict) -> dict:
    """Build the package and write it as robot_requests/<id>.package.json."""
    out = pkg.build(s, req, agent.robot)
    d = agent.cfg.data_dir / "robot_requests"
    d.mkdir(exist_ok=True)
    (d / f"{req['proposal']['id']}.package.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


def fill(agent, sid: str) -> None:
    """When the recipe lists no materials or equipment, the agent reads them off
    its own steps; the package is rebuilt with them."""
    s = agent.load(sid)
    req = s["phases"]["robot"].get("request") or {}
    rc = req.get("recipe") or {}
    if not rc or (rc.get("materials") and rc.get("equipment")) or not agent.cfg.llm:
        return
    ans = agent.cfg.llm.role(steps.role("robot", "materials")).ask(
        "You prepare a protocol package for a self-building lab. From the recipe, list every material "
        "(chemicals, stocks, solvents, substrates; name, amount, role) and every piece of equipment or tool "
        "(instruments, vessels, measuring tools) it needs. Only what the recipe implies; no extras.",
        json.dumps({"material": s["problem"].get("material"), "method": s["problem"].get("method"),
                    "conditions": req["proposal"].get("conditions"), "recipe": rc}), FILL)
    if not ans.get("materials") and not ans.get("equipment"):
        return

    def put(s):
        R = s["phases"]["robot"]["request"]["recipe"]
        for k in ("materials", "equipment"):
            R[k] = R.get(k) or ans.get(k) or []
        if (s["phases"]["recipe"].get("recipe") or {}).get("title") == R.get("title"):
            s["phases"]["recipe"]["recipe"].update({k: R[k] for k in ("materials", "equipment")})
        s["phases"]["robot"]["package"] = package(agent, s, s["phases"]["robot"]["request"])
    agent.mutate(sid, put)


def result(agent, sid: str, body: dict) -> dict:
    """Record one run's measurements, compare with the predicted bands, complete the study."""
    measured = {q: float(v) for q, v in (body.get("measured") or {}).items() if v not in (None, "")}
    if not measured:
        raise ValueError("no measured values")
    notes = str(body.get("notes") or "").strip()

    def put(s):
        rb = s["phases"]["robot"]
        req = rb.get("request")
        if not req:
            raise ValueError("no robot request for this study")
        p = req["proposal"]
        rows = []
        for q, v in measured.items():
            b = p["predicted"].get(q)
            rows.append({"quantity": q, "measured": v, "predicted": b,
                         "inside": bool(b["low"] <= v <= b["high"]) if b else None})
        runs = rb.setdefault("runs", [])
        runs.append({"n": len(runs) + 1, "at": time.time(), "rows": rows, "notes": notes})
        rb["results"] = rows
        rb["status"] = "done"
        s["status"] = "complete"
        recipe = {"recipe_id": f"robot:{sid}:{p['id']}:{len(runs)}", "source": "robot",
                  "paper_title": f"robot run {p['id']} #{len(runs)}",
                  "material": s["problem"]["material"], "method": p["method"], "conditions": p["conditions"],
                  "outcomes": [{"quantity": q, "value": v, "unit": (p["predicted"].get(q) or {}).get("unit", ""),
                                "method": "robot"} for q, v in measured.items()]}
        with open(agent.cfg.data_dir / "feedback.jsonl", "a") as fh:
            fh.write(json.dumps(recipe) + "\n")
        banded = [r for r in rows if r["inside"] is not None]
        n_in = sum(r["inside"] for r in banded)
        cmp = (f"{n_in} of {len(banded)} fall inside the predicted band" if banded
               else "this recipe had no model band, so compare them with your targets")
        s["chat"].append({"role": "agent", "phase": "robot", "at": time.time(),
                          "text": f"Run {len(runs)}: recorded {len(rows)} measurements; {cmp}. The run is now a "
                                  "library recipe, so the next study calibrates on it."})
    agent.mutate(sid, put)
    agent._lib = None
    agent.reflect_async(sid, "robot", body, trigger="robot result")   # results vs predicted bands
    return {"ok": True}
