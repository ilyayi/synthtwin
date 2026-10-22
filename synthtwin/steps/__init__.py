"""The pipeline steps: one folder per UI step, in order.

    goal    agree a measurable goal with the researcher
    prior   related studies: what was swept, what came out
    stack   the simulation stack at three scales, and its chain
    sample  the benchmark sample the stack must predict
    bench   build + QA + score the stack on the sample
    case    the researcher's case: maps, sensitivities, proposals
    recipe  the recipe to run, and alternatives
    robot   hand-off to the robotic platform, results back

Each folder holds everything the step needs: step.json (the registry data
below), protocol.md (its versioned protocol), schema.py (the LLM's JSON
schema for the step + cleaning), run.py (the step's handlers, called by the
engine orchestrator), panel.js / panel.css (its UI panel). The engine's phase
list, the UI stepper and the protocol phase mapping all read step.json, so
this is the one source of truth for the pipeline's shape.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

HERE = Path(__file__).parent

# which team role ("plan" = frontier, "work" = light) makes each kind of LLM call;
# a step's step.json "models" overrides its kinds (steps without one get these)
MODEL_ROLES = {"turn": "plan", "build": "work", "review": "plan", "lit": "work",
               "triage": "work", "materials": "work", "refine": "work"}


def _load() -> list[dict]:
    steps = []
    for d in sorted(HERE.iterdir()):
        f = d / "step.json"
        if not f.is_file():
            continue
        s = json.loads(f.read_text())
        if s.get("id") != d.name:
            raise ValueError(f"{f}: declares id {s.get('id')!r}, expected {d.name!r}")
        for kind, role in (s.get("models") or {}).items():
            if kind not in MODEL_ROLES:
                raise ValueError(f"{f}: models kind {kind!r} is not one of {sorted(MODEL_ROLES)}")
            if role not in ("plan", "work"):
                raise ValueError(f"{f}: models.{kind} must be 'plan' or 'work', not {role!r}")
        steps.append(s)
    steps.sort(key=lambda s: s["order"])
    if [s["order"] for s in steps] != list(range(1, len(steps) + 1)):
        raise ValueError("step.json orders must be 1..n without gaps")
    return steps


STEPS: list[dict] = _load()
ORDER: list[str] = [s["id"] for s in STEPS]
BY_ID: dict[str, dict] = {s["id"]: s for s in STEPS}

_modules: dict[str, importlib.util.ModuleType | None] = {}


def get(sid: str) -> dict:
    """The step's registry entry (its step.json)."""
    try:
        return BY_ID[sid]
    except KeyError:
        raise ValueError(f"no step {sid!r} (have: {', '.join(ORDER)})") from None


def role(sid: str, kind: str) -> str:
    """Which team role ("plan" | "work") makes this kind of LLM call in this step
    (the step.json "models" map, else the MODEL_ROLES default for the kind)."""
    r = get(sid).get("models", {}).get(kind)
    if r not in (None, "plan", "work"):
        raise ValueError(f"step {sid!r}: models.{kind} must be 'plan' or 'work', not {r!r}")
    return r or MODEL_ROLES[kind]


def folder(sid: str) -> Path:
    """The step's folder (its protocol.md, panel.js, panel.css live there)."""
    get(sid)
    return HERE / sid


def module(sid: str, name: str):
    """One of the step's code modules ("run" or "schema"), imported lazily."""
    key = f"{sid}.{name}"
    if key not in _modules:
        _modules[key] = importlib.import_module(f"synthtwin.steps.{key}")
    return _modules[key]


def run(sid: str):
    """The step's handlers: apply(agent, s, ans), confirm(agent, sid, s, body),
    work(agent, sid) for the background job of the phase."""
    return module(sid, "run")


def schema(sid: str):
    """The step's LLM schemas ({engine key: JSON schema}) and cleaning helpers."""
    return module(sid, "schema")


def llm_schema(extra: dict, required: list[str]) -> dict:
    """The wrapper every step's LLM schema uses: a reply, a ready flag, the patch."""
    return {"type": "object",
            "properties": {"reply": {"type": "string"}, "ready": {"type": "boolean"}, **extra},
            "required": ["reply", "ready", *required]}
