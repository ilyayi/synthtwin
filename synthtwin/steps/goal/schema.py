"""The goal step's LLM schema: the problem patch (targets, knobs, fixed
conditions) the agent writes from the researcher's text, plus the cleaning
that turns a patch into a study problem and checks it is complete."""
from __future__ import annotations

from synthtwin import steps
from synthtwin.core import systems

GOAL_PATCH = {
    "type": "object",
    "properties": {
        "system": {"type": "string", "enum": ["colloid", "other"]},
        "material": {"type": "string"}, "method": {"type": "string"},
        "targets": {"type": "array", "items": {"type": "object", "properties": {
            "quantity": {"type": "string"}, "aim": {"type": "string", "enum": ["equal", "at_most", "at_least"]},
            "value": {"type": "number"}}, "required": ["quantity", "aim", "value"]}},
        "knobs": {"type": "array", "items": {"type": "object", "properties": {
            "key": {"type": "string"}, "lo": {"type": "number"}, "hi": {"type": "number"}}, "required": ["key", "lo", "hi"]}},
        "fixed": {"type": "array", "items": {"type": "object", "properties": {
            "key": {"type": "string"}, "value": {"type": "number"}}, "required": ["key", "value"]}},
        "title": {"type": "string", "description": "short study title, under 60 characters"},
    },
    "required": ["system", "material", "method", "targets", "knobs", "fixed", "title"],
}

SCHEMAS = {"goal": steps.llm_schema({"problem": GOAL_PATCH}, ["problem"])}


def problem_from_patch(p: dict, text: str) -> dict:
    targets: dict[str, dict] = {}
    for t in p.get("targets") or []:
        d = targets.setdefault(t["quantity"], {})
        d[{"equal": "value", "at_most": "max", "at_least": "min"}[t["aim"]]] = float(t["value"])
    return {"text": text, "system": p.get("system") or "colloid", "material": p.get("material", ""),
            "method": p.get("method", ""),
            "targets": targets, "knobs": {k["key"]: [float(k["lo"]), float(k["hi"])] for k in p.get("knobs") or []},
            "fixed": {f["key"]: float(f["value"]) for f in p.get("fixed") or []}, "title": p.get("title", "")}


def check_problem(pb: dict) -> list[str]:
    errs = []
    if not pb.get("material"):
        errs.append("no material")
    if not pb.get("targets"):
        errs.append("no target quantity")
    if not pb.get("knobs"):
        errs.append("no knob to vary")
    for k, (lo, hi) in (pb.get("knobs") or {}).items():
        if not lo < hi:
            errs.append(f"knob {k}: low {lo:g} is not below high {hi:g}")
    if not systems.is_builtin(pb):
        return errs + systems.check_generic(pb)
    from synthtwin.lib.design.problem import KNOWN_QUANTITIES, is_condition_key
    for k in [*(pb.get("knobs") or {}), *(pb.get("fixed") or {})]:
        if not is_condition_key(k):
            errs.append(f"{k} is not a condition key the simulator knows (use one from the list)")
    for q in pb.get("targets") or {}:
        if q not in KNOWN_QUANTITIES:
            errs.append(f"{q} is not a quantity the simulator predicts")
    return errs
