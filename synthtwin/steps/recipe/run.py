"""The recipe step's handlers: apply (the recipe the agent wrote, and its
choice of proposal) and confirm (the gate into robot: the protocol package is
written for the robotic platform)."""
from __future__ import annotations

import json
import time
from typing import Callable


def apply(agent, s: dict, ans: dict) -> Callable | None:
    """Record the recipe; the choice must be one of the optimiser's proposals."""
    P = s["phases"]["recipe"]
    if not ans.get("recipe"):
        return None
    P["recipe"] = ans["recipe"]
    ids = [p["id"] for p in s["phases"]["case"].get("proposals", [])]
    P["choice"] = ans.get("choice") if ans.get("choice") in ids else (ids[0] if ids else None)
    return None


def confirm(agent, sid: str, s: dict, body: dict) -> None:
    """The gate: the picked proposal (or the agent's own recipe) becomes a robot
    request file the platform team hands to the robot."""
    R = s["phases"]["recipe"]
    props = {p["id"]: p for p in s["phases"]["case"].get("proposals", [])}
    pid = body.get("proposal_id") or R.get("choice") or ("agent" if R.get("recipe") else None)
    if pid == "agent" and R.get("recipe"):   # the agent's own write-up (e.g. a literature bracket), no model band
        rc = R["recipe"]
        pid = f"{sid}-agent"
        props[pid] = {"id": pid, "method": (s.get("problem") or {}).get("method", ""), "conditions": {},
                      "predicted": {}, "steps": rc.get("steps", []), "label": "agent recipe"}
        R = {**R, "choice": pid}
    if pid not in props:
        raise ValueError("pick a proposal to send")
    req = {"study": sid, "at": time.time(), "robot": agent.robot.get("name", ""), "proposal": props[pid],
           "recipe": R.get("recipe") if pid == R.get("choice") else None,
           "label": props[pid].get("label", "exploratory"), "status": "requested",
           "handoff": "Protocol package for a self-building lab (e.g. Self-Building Labs): it checks the steps "
                      "against its capabilities, builds and tests any it lacks in its digital twin, runs the "
                      "protocol once approved, and returns measurements and run logs here, where they feed "
                      "the library."}
    out = agent.cfg.data_dir / "robot_requests"
    out.mkdir(exist_ok=True)
    (out / f"{pid}.json").write_text(json.dumps(req, indent=1, default=str))

    def go(s):
        agent._advance(s, "robot")
        s["phases"]["robot"].update(request=req, status="awaiting_user")
        s["status"] = "awaiting_user"
        s["chat"].append({"role": "agent", "phase": "robot", "at": time.time(),
                          "text": f"Request {pid} is written for the robot ({req['label']}). Hand it to the platform "
                                  "team; when the measurements are back, enter them below and I will compare them "
                                  "with the prediction."})
    agent.mutate(sid, go)
