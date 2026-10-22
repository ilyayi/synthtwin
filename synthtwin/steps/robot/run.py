"""The robot step's handler: result (the researcher enters the robot's
measurements; they are compared with the prediction and fed back into the
library)."""
from __future__ import annotations

import json
import time


def result(agent, sid: str, body: dict) -> dict:
    """Record the measurements, compare with the predicted bands, complete the study."""
    measured = {q: float(v) for q, v in (body.get("measured") or {}).items() if v not in (None, "")}
    if not measured:
        raise ValueError("no measured values")

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
        rb["results"] = rows
        rb["status"] = "done"
        s["status"] = "complete"
        recipe = {"recipe_id": f"robot:{sid}:{p['id']}", "source": "robot", "paper_title": f"robot run {p['id']}",
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
                          "text": f"Recorded {len(rows)} measurements; {cmp}. The run is now a library recipe, "
                                  "so the next study calibrates on it."})
    agent.mutate(sid, put)
    agent._lib = None
    return {"ok": True}
