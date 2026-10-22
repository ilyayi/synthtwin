"""The goal step's handlers: what the agent does with its turn's answer
(apply: record the problem it wrote) and what confirming the goal does to the
study (confirm: the gate into prior)."""
from __future__ import annotations

from typing import Callable

from synthtwin import steps
from synthtwin.core import runner, systems
from synthtwin.steps.goal.schema import check_problem, problem_from_patch


def apply(agent, s: dict, ans: dict) -> Callable | None:
    """Record the problem the agent wrote; if it fails validation, ask for one fix."""
    if not ans.get("problem"):
        return None
    P = s["phases"]["goal"]
    pb = problem_from_patch(ans["problem"], s["text"])
    if not (pb["material"] or pb["targets"]):
        return None
    s["problem"] = pb
    if pb.get("title"):
        s["title"] = pb["title"]
    P["errors"] = check_problem(pb)
    tries = P.get("fix_tries", 0)
    if P["errors"] and tries < 1:
        P["fix_tries"] = tries + 1
        sid, errs = s["id"], "; ".join(P["errors"])
        how = ("canonical keys only; drop what the simulator does not model" if systems.is_builtin(pb)
               else "snake_case keys ending in their unit")
        return lambda: agent.turn(sid, f"The goal you wrote fails validation: {errs}. Fix it ({how}) "
                                       "and reply briefly.")
    if not P["errors"]:
        P["fix_tries"] = 0
    return None


def confirm(agent, sid: str, s: dict, body: dict) -> None:
    """The gate: the problem must be complete; defaults are filled in, knobs are
    clipped to the robot, then the search for related studies starts."""
    pb = s.get("problem") or {}
    errs = check_problem(pb)
    if errs:
        raise ValueError("the goal is not complete yet: " + "; ".join(errs))
    notes = []
    for k, v in (runner.DEFAULT_FIXED.items() if systems.is_builtin(pb) else ()):
        if k not in pb["fixed"] and k not in pb["knobs"]:
            pb["fixed"][k] = v
            notes.append(f"{k}={v:g} (default)")
    lims = (("temperature_C", agent.robot.get("temperature_C")),
            ("total_volume_ml", agent.robot.get("volume_ml")))
    for key, lim in (lims if systems.is_builtin(pb) else ()):
        rng = pb["knobs"].get(key)
        if lim and rng and (rng[0] < lim[0] or rng[1] > lim[1]):
            new = [max(rng[0], lim[0]), min(rng[1], lim[1])]
            if new[0] < new[1]:
                pb["knobs"][key] = new
                notes.append(f"{key} clipped to the robot's [{new[0]:g}, {new[1]:g}]")

    def go(s):
        s["problem"] = pb
        s["phases"]["goal"]["notes"] = notes
        agent._advance(s, "prior")
    agent.mutate(sid, go)
    agent.background(sid, "finding related studies", lambda: steps.run("prior").work(agent, sid))
