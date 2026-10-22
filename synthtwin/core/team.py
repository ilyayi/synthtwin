"""A team of backends: the frontier model plans, light models work.

    Team       plan and work backends behind one ask/build interface. .role(name)
               picks one ("plan" | "work"); single backends answer .role() with
               themselves, so callers can always route llm.role("work").ask(...).
               Every answer's _meta records which backend, model and role produced it.

    delegate   the plan-spawns-workers pattern: the plan model splits a goal into
               subtasks (disjoint files, each with an acceptance check command),
               work models execute them in parallel, and the plan model reviews
               the results against the checks — accepting or sending ONE fix-up
               round back to the workers that need it.
"""
from __future__ import annotations

import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from synthtwin.core.llm import LLMError


class Team:
    kind = "team"

    def __init__(self, plan: Any, work: Any):
        self.plan, self.work = plan, work
        self.name = f"{plan.name}/{work.name}"

    @property
    def mixed(self) -> bool:
        """True when plan and work really are different models (delegate applies)."""
        return self.plan is not self.work

    def role(self, name: str = "plan") -> Any:
        b = self.work if name == "work" else self.plan
        b._role = name   # recorded in every answer's _meta
        return b

    def ask(self, *a: Any, **kw: Any) -> dict:      # a plain ask is a planning turn
        return self.role("plan").ask(*a, **kw)

    def build(self, *a: Any, **kw: Any) -> dict:    # a plain build is a worker's
        return self.role("work").build(*a, **kw)


SPLIT_SYSTEM = ("You are the planning half of a build team: a frontier model that splits work for lighter "
                "models to execute. Split the goal into a few independent subtasks (typically one per method "
                "or component). Each must be self-contained, own disjoint files, and end with a check the "
                "platform can run: a shell command in the subtask's own folder that exits 0 when the subtask "
                "is done. Never put two subtasks' outputs in the same file.")
SPLIT_SCHEMA = {
    "type": "object",
    "properties": {"subtasks": {"type": "array", "items": {"type": "object", "properties": {
        "title": {"type": "string"},
        "instructions": {"type": "string", "description": "self-contained: what to build or run, and to what end"},
        "files": {"type": "array", "items": {"type": "string"},
                  "description": "paths this subtask may touch, relative to its own folder"},
        "check": {"type": "string", "description": "shell command, exit 0 = done, run in its own folder"}},
        "required": ["title", "instructions", "check"]}}},
    "required": ["subtasks"]}
REVIEW_SYSTEM = ("You are the planning half of a build team, reviewing what the worker models did with your "
                 "subtasks. For each: read the worker's summary and its acceptance check output, and either "
                 "accept it, or verdict fix with exact, doable instructions (one round only).")
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {"reviews": {"type": "array", "items": {"type": "object", "properties": {
        "title": {"type": "string"},
        "verdict": {"type": "string", "enum": ["accept", "fix"]},
        "instructions": {"type": "string", "description": "what to fix, when the verdict is fix"}},
        "required": ["title", "verdict"]}}},
    "required": ["reviews"]}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:24] or "task"


def _run_check(cmd: str, cwd: Path, timeout: int = 900) -> dict:
    try:
        r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "out": f"check timed out after {timeout} s"}
    except OSError as exc:
        return {"ok": False, "out": f"{type(exc).__name__}: {exc}"}
    return {"ok": r.returncode == 0, "out": (r.stdout + r.stderr)[-1200:].strip()}


def delegate(team: Any, goal: str, context: str, workdir: Path, n_max: int = 4,
             timeout: int | None = None, progress: Any = None) -> dict:
    """Plan -> workers -> check. Returns {subtasks: [{title, dir, llm, model, rounds,
    check: {ok, out}, text, accepted, cost_usd}], accepted, fixed, cost_usd, seconds}.
    The plan model splits `goal` (with `context` for the details); each work model runs
    one subtask in workdir/NN-slug/ (parallel threads, disjoint files); the plan model
    reviews every result against its acceptance check and may send the failed ones ONE
    fix-up round."""
    workdir = Path(workdir)
    split = team.role("plan").ask(SPLIT_SYSTEM, f"GOAL:\n{goal}\n\nCONTEXT:\n{context[:20000]}\n\n"
                                  f"Split this into at most {n_max} subtasks.", SPLIT_SCHEMA)
    subs = [s for s in (split.get("subtasks") or []) if isinstance(s, dict)
            and s.get("title") and s.get("instructions")][:n_max]
    if not subs:
        raise LLMError("the plan model returned no subtasks to delegate")
    t0 = time.time()
    lock, results = threading.Lock(), [None] * len(subs)

    def one(i: int, sub: dict) -> None:
        d = workdir / f"{i + 1:02d}-{_slug(sub['title'])}"
        d.mkdir(parents=True, exist_ok=True)
        files = ", ".join(sub.get("files") or []) or "everything in this folder"
        w = team.role("work")
        prompt = (f"GOAL (the whole job, for context):\n{goal}\n\nYOUR SUBTASK: {sub['title']}\n"
                  f"{sub['instructions']}\n\nYou may touch only: {files} (other subtasks own the rest; "
                  f"work in this folder only: {d.name}/).\n\nCONTEXT:\n{context[:20000]}\n\n"
                  f"When you are done, `{sub.get('check', '')}` must exit 0 in this folder.")
        try:
            r = w.build(prompt, d, timeout=timeout)
        except Exception as exc:   # a failed worker must not take the others down
            r = {"text": f"{type(exc).__name__}: {exc}", "llm": w.name, "model": getattr(w, "model", w.name)}
        with lock:
            results[i] = {"title": sub["title"], "dir": d.name, "llm": r.get("llm") or w.name,
                          "model": r.get("model") or getattr(w, "model", w.name), "rounds": 1,
                          "cost_usd": r.get("cost_usd") or 0, "text": (r.get("text") or "")[-600:],
                          "check": _run_check(sub.get("check", "true"), d), "fix": ""}

    threads = [threading.Thread(target=one, args=(i, sub), daemon=True) for i, sub in enumerate(subs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if progress:
        progress()
    rev = team.role("plan").ask(REVIEW_SYSTEM, "GOAL:\n" + goal + "\n\nSubtask results to review:\n" + "\n\n".join(
        f"## {r['title']}\nAcceptance check ({'exit 0' if r['check']['ok'] else 'FAILED'}):\n{r['check']['out'][-600:]}\n"
        f"Worker's summary:\n{r['text']}" for r in results) + "\n\nAccept each, or send one fix round.", REVIEW_SCHEMA)
    fixes = {r.get("title"): r for r in (rev.get("reviews") or []) if r.get("verdict") == "fix"}
    fixed = []
    if fixes:
        for sub, r in zip(subs, results):
            f = fixes.get(r["title"])
            if not f:
                continue
            d = workdir / r["dir"]
            w = team.role("work")
            try:
                rr = w.build(f"One fix round for your subtask {r['title']} (the whole job, for context: "
                             f"{goal}). The reviewer's instructions:\n{f.get('instructions', '')}\n\n"
                             f"Your own summary of what you did:\n{r['text']}", d, timeout=timeout)
                r["text"] = (rr.get("text") or r["text"])[-600:]
                r["llm"], r["model"] = rr.get("llm") or r["llm"], rr.get("model") or r["model"]
            except Exception as exc:
                r["text"] += f"\n(fix round failed: {type(exc).__name__}: {exc})"
            r["check"] = _run_check(sub.get("check", "true"), d)
            r["rounds"] += 1
            r["fix"] = str(f.get("instructions", ""))[:400]
            fixed.append(r["title"])
        if progress:
            progress()
    for r in results:
        r["accepted"] = r["title"] not in fixed or r["check"]["ok"]
        del r["fix"]
    return {"subtasks": results, "accepted": [r["title"] for r in results if r["accepted"]],
            "fixed": fixed, "cost_usd": round(sum(r["cost_usd"] for r in results), 3),
            "seconds": round(time.time() - t0, 1)}
