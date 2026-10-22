"""Build a simulator for a system the platform has no model for.

A Claude Code session works in the study's own folder with the tools this
machine has (tools.yaml: Python, LAMMPS, Quantum ESPRESSO, ...). It carries
out the stack the researcher approved (mechanistic model, MD, DFT, kMC,
surrogate on literature data, ...), and assembles the results into model.py,
which follows the predictor contract in synthtwin.agent.systems. It also
writes report.json: what each method ran or looked up, the values it fed
into the model, and the model's known limits.

The benchmark studies are held out: the builder sees their conditions and
anchor point only, never their other outcomes, so the benchmark that follows
is a fair test of what it built.

There is no time limit by default. Long simulations run detached through
simjob.py (written into the folder), so they outlive the builder's session:
the builder launches them and ends its turn, the platform waits for them
(hours or days), pausing GPU jobs when a GPU runs hot, then resumes the
builder from its NOTES.md. When the model passes its contract check, a
separate reviewer agent audits every method (did it run, is it converged
and sampled well enough, are the numbers physical, does model.py match the
results) and sends fixes back to the builder until it passes or the review
rounds run out.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import yaml

from synthtwin.core.toolbox import tools_text
from synthtwin.core.team import Team, delegate

from synthtwin import protocols, steps

CHECK = r'''"""Contract check for model.py (run by the builder and by the platform)."""
import json, math, sys
sys.path.insert(0, ".")
import model
spec = json.load(open("spec.json"))
cond = {**spec["fixed"], **{k: (lo + hi) / 2 for k, (lo, hi) in spec["knobs"].items()}}
out = model.predict({"material": spec["material"], "method": spec["method"], "conditions": cond,
                     "calibration": None, "n_draws": 8})
missing = [q for q in spec["targets"] if q not in out]
bad = [q for q, b in out.items() if not all(isinstance(b.get(k), (int, float)) and math.isfinite(b[k])
                                             for k in ("value", "low", "high"))]
assert not missing, f"predict() does not return {missing}"
assert not bad, f"non-finite value/low/high for {bad}"
for k, (lo, hi) in spec["knobs"].items():   # the whole box must evaluate
    for v in (lo, hi):
        model.predict({"material": spec["material"], "method": spec["method"],
                       "conditions": {**cond, k: v}, "calibration": None, "n_draws": 8})
if hasattr(model, "calibrate") and spec["anchors"]:
    a = spec["anchors"][0]
    cal = model.calibrate({"material": spec["material"], "method": spec["method"],
                           "conditions": {**spec["fixed"], **a["conditions"]}}, a["outcomes"])
    json.dumps(cal)
    model.predict({"material": spec["material"], "method": spec["method"], "conditions": cond,
                   "calibration": cal, "n_draws": 8})
print("OK", json.dumps({q: round(b["value"], 4) for q, b in out.items()}))
'''

SIMJOB = r'''"""Run long simulation jobs detached from your session (they keep running when it ends).

    python simjob.py start ID [--gpu N] -- COMMAND...   runs COMMAND in the current folder; log in jobs/ID/log
        COMMAND is one quoted shell string ('cd md && run.sh') or plain words (bash -c '...' keeps its quoting)
    python simjob.py status                              one line per job: id, state, minutes, last log line

Pass --gpu N for GPU jobs: the platform pauses them while that GPU is too hot.
"""
import json, os, shlex, subprocess, sys, time
from pathlib import Path
J = Path(__file__).resolve().parent / "jobs"


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def state(m):
    d = J / m["id"]
    if (d / "rc").exists():
        return "done rc=" + (d / "rc").read_text().strip()
    return ("paused (GPU hot)" if m.get("paused") else "running") if alive(m["pid"]) else "lost"


if sys.argv[1:2] == ["start"]:
    a = sys.argv[2:]
    jid, gpu = a[0], None
    if "--gpu" in a[:a.index("--")]:
        gpu = int(a[a.index("--gpu") + 1])
    words = a[a.index("--") + 1:]
    cmd = words[0] if len(words) == 1 else shlex.join(words)
    d = J / jid
    if (d / "meta.json").exists() and state(json.loads((d / "meta.json").read_text())).startswith(("running", "paused")):
        sys.exit(f"job {jid} is still running")
    d.mkdir(parents=True, exist_ok=True)
    (d / "rc").unlink(missing_ok=True)
    log = open(d / "log", "w")
    (d / "cmd.sh").write_text(cmd + "\n")   # a syntax error then still records rc (else the job looks "lost")
    p = subprocess.Popen(["bash", "-c", f"bash {shlex.quote(str(d / 'cmd.sh'))}; echo $? > {shlex.quote(str(d / 'rc'))}"],
                         cwd=os.getcwd(), stdout=log,
                         stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    (d / "meta.json").write_text(json.dumps({"id": jid, "cmd": cmd, "cwd": os.getcwd(), "pid": p.pid,
                                             "gpu": gpu, "started": time.time()}))
    print(f"started {jid} (pid {p.pid}); log: jobs/{jid}/log")
elif sys.argv[1:2] == ["status"]:
    for f in sorted(J.glob("*/meta.json")):
        m = json.loads(f.read_text())
        tail = (f.parent / "log").read_text(errors="replace").strip().splitlines()[-1:] if (f.parent / "log").exists() else []
        print(m["id"], state(m), f"{(time.time() - m['started']) / 60:.0f} min", (tail[0] if tail else "")[:120], sep=" | ")
else:
    print(__doc__)
'''

# the prompt text lives in synthtwin/protocols/build-and-qa.md (the build-and-qa protocol)
BRIEF = protocols.prompt("builder.brief")
TIME_LIMITED = protocols.prompt("builder.time_limited")
NO_LIMIT = protocols.prompt("builder.no_limit")
RESUME = protocols.prompt("builder.resume")
REVIEW = protocols.prompt("builder.review")
ASSEMBLE = protocols.prompt("builder.assemble")   # mixed teams: the workers' folders, for the assembler

QA_SCHEMA = {
    "type": "object",
    "properties": {
        "overall": {"type": "string", "enum": ["pass", "fix", "fail"]},
        "summary": {"type": "string"},
        "methods": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "verdict": {"type": "string", "enum": ["pass", "fix", "fail", "skipped"]},
            "checks": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "ok": {"type": "boolean"}, "evidence": {"type": "string"}},
                "required": ["name", "ok", "evidence"]}},
            "fixes": {"type": "array", "items": {"type": "string"}}},
            "required": ["id", "verdict", "checks", "fixes"]}},
        "model": {"type": "object", "properties": {
            "verdict": {"type": "string", "enum": ["pass", "fix", "fail"]},
            "issues": {"type": "array", "items": {"type": "string"}}}, "required": ["verdict", "issues"]},
    },
    "required": ["overall", "summary", "methods", "model"],
}




def _studies(studies: list[dict], held: set[str], targets: list[str]) -> tuple[str, str, list[dict]]:
    train, hold, anchors = [], [], []
    for x in studies:
        if x.get("source") == "benchmark":   # sealed cards of the built-in system
            continue
        pts = [p for p in x.get("points", []) if p.get("outcomes")]
        if x["id"] in held:
            from synthtwin.steps.bench.bench import study_to_case
            got = study_to_case(json.loads(json.dumps(x)), targets)
            if not got:
                continue
            card = got[0]
            anchor = next(p for p in card["points"] if p["label"] == card["anchor_label"])
            ao = [{"quantity": o["quantity"], "value": o["value"]} for o in card["anchor_outcomes"]]
            anchors.append({"conditions": anchor["conditions"], "outcomes": ao})
            hold.append(json.dumps({"title": x["title"], "swept": card["sweep_variable"],
                                    "points": [p["conditions"] for p in card["points"]],
                                    "anchor": {"conditions": anchor["conditions"], "outcomes": ao}}))
        elif pts:
            train.append(json.dumps({"title": x["title"], "url": x.get("url", ""), "material": x.get("material"),
                                     "method": x.get("method"), "fixed": x.get("fixed"),
                                     "points": [{"c": p["conditions"], "o": p["outcomes"]} for p in pts[:30]]}))
    return "\n".join(train) or "(none)", "\n".join(hold) or "(none)", anchors


def jobs(workdir: Path) -> list[dict]:
    """Jobs launched through simjob.py, with their state and last log line."""
    out = []
    for f in sorted((Path(workdir) / "jobs").glob("*/meta.json")):
        try:
            m = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        d = f.parent
        if (d / "rc").exists():
            st = "done" if (d / "rc").read_text().strip() == "0" else "failed"
        else:
            st = ("paused" if m.get("paused") else "running") if _alive(m["pid"]) else "lost"
        tail = ""
        if (d / "log").exists():
            with open(d / "log", "rb") as fh:
                fh.seek(max(0, (d / "log").stat().st_size - 400))
                lines = fh.read().decode(errors="replace").strip().splitlines()
                tail = lines[-1][:160] if lines else ""
        out.append({"id": m["id"], "state": st, "gpu": m.get("gpu"), "pid": m["pid"],
                    "minutes": round((time.time() - m["started"]) / 60, 1), "tail": tail})
    return out


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:   # a zombie counts as finished
        return Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


def gpu_temps() -> dict[int, float]:
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=index,temperature.gpu", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=20)
        return {int(a): float(b) for a, b in (ln.split(",") for ln in r.stdout.strip().splitlines() if "," in ln)}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


def gpu_guard(workdir: Path, hot: float = 83, cool: float = 75) -> None:
    """Pause GPU jobs on a GPU at or above `hot` degrees C; resume them below `cool`."""
    metas = [(f, json.loads(f.read_text())) for f in (Path(workdir) / "jobs").glob("*/meta.json")]
    metas = [(f, m) for f, m in metas if m.get("gpu") is not None and not (f.parent / "rc").exists() and _alive(m["pid"])]
    if not metas:
        return
    temps = gpu_temps()
    for f, m in metas:
        t = temps.get(m["gpu"])
        if t is None:
            continue
        sig = signal.SIGSTOP if t >= hot and not m.get("paused") else signal.SIGCONT if t < cool and m.get("paused") else None
        if sig is None:
            continue
        try:
            os.killpg(m["pid"], sig)
        except OSError:
            continue
        m["paused"] = sig == signal.SIGSTOP
        f.write_text(json.dumps(m))


def stop_jobs(workdir: Path) -> None:
    for j in jobs(workdir):
        if j["state"] in ("running", "paused"):
            for sig in (signal.SIGCONT, signal.SIGTERM):
                try:
                    os.killpg(j["pid"], sig)
                except OSError:
                    pass


def chain_text(chain: list[dict] | None) -> str:
    """The approved chain for the brief: model.py composes these links in order, each a function with its inputs
    and outputs, so a failing link can be found and swapped (competing mechanisms are scored by the benchmark)."""
    if not chain:
        return ""
    out = ["", "## The chain (build model.py as these links, in this order; each link one function from its "
           "inputs to its outputs)"]
    for i, c in enumerate(chain, 1):
        out.append(f"{i}. {c['id']}: {c.get('name', '')}. {c.get('physics', '')} "
                   f"In: {', '.join(c.get('inputs') or [])}. Out: {', '.join(c.get('outputs') or [])}. "
                   f"Sensitivity {c.get('sensitivity', '?')}: {c.get('why', '')}")
        if c.get("competing"):
            out.append("   Competing mechanisms (implement each as an option; keep the one the training data favour "
                       "and report the others): " + "; ".join(c["competing"]))
        if c.get("lessons"):
            out.append("   Lessons from similar simulation studies: " + "; ".join(c["lessons"]))
    return "\n".join(out) + "\n"


def _delegate_text(d: dict) -> str:
    """The subtasks' folders and outcomes, for the assembly note."""
    return "\n".join(f"- {t['dir']}/ — {t['title']}: acceptance check "
                     f"{'passed' if t['check']['ok'] else 'FAILED'} after {t['rounds']} round(s) "
                     f"(model {t.get('model', '?')}). Worker's summary: {t['text'][:300]}"
                     for t in d.get("subtasks", [])) or "(no subtasks came back)"


def build(llm: Any, workdir: Path, problem: dict, stack: list[dict], studies: list[dict], held: set[str],
          tools_path: Path | None, budget_min: int = 0, qa_rounds: int = 3,
          progress: Callable[[dict], None] | None = None, poll: float = 60, toolbox: Path | None = None,
          chain: list[dict] | None = None) -> dict:
    """Run the builder (and its jobs) until model.py passes, then the QA review loop.

    budget_min=0 means no time limit. progress() gets {stage, round, jobs, sessions, qa,
    delegate?} as work goes on. A mixed team (plan != work) first delegates the methods
    to worker subtasks, then one assembly session builds model.py from them."""
    workdir.mkdir(parents=True, exist_ok=True)
    train, hold, anchors = _studies(studies, held, list(problem["targets"]))
    spec = {"material": problem.get("material", ""), "method": problem.get("method", ""),
            "targets": list(problem["targets"]), "knobs": problem["knobs"], "fixed": problem.get("fixed") or {},
            "anchors": anchors}
    (workdir / "spec.json").write_text(json.dumps(spec, indent=1))
    (workdir / "check_model.py").write_text(CHECK)
    (workdir / "simjob.py").write_text(SIMJOB)
    from synthtwin.core import toolbox as tb
    if toolbox:
        toolbox = tb.ensure(toolbox)
    goal = json.dumps({k: problem.get(k) for k in ("text", "system", "material", "method", "targets", "knobs",
                                                     "fixed", "units")}, indent=1)
    st = "\n".join(f"- {m['id']}: {m['name']} ({m.get('tool', '')}). Feeds: {m.get('feeds', m.get('insight', ''))}"
                   + (f" [link: {m['link']}]" if m.get("link") else "") + (f" Gate: {m['check']}" if m.get("check") else "")
                   for m in stack if m.get("selected"))
    time_rule = TIME_LIMITED.format(budget=budget_min) if budget_min else NO_LIMIT
    prompt = BRIEF.format(goal=goal, stack=st or "- a mechanistic model fitted to the training data", chain=chain_text(chain),
                          tools=tools_text(tools_path, toolbox), train=train, held=hold, targets=", ".join(spec["targets"]),
                          knobs=json.dumps(problem["knobs"]), fixed=json.dumps(spec["fixed"]), time_rule=time_rule,
                          install_rule=tb.policy(toolbox, problem.get("problem_id", workdir.name)))
    resuming = (workdir / "NOTES.md").is_file() and (workdir / "BRIEF.md").is_file()
    (workdir / "BRIEF.md").write_text(prompt)
    t0 = time.time()
    deadline = t0 + budget_min * 60 if budget_min else None
    log: dict[str, Any] = {"sessions": [], "qa": [], "stage": "building", "round": 0}
    cost = [0.0]
    # the bench step.json "models" routing: work builds, the plan model reviews QA
    worker = llm.role(steps.role("bench", "build"))
    reviewer = llm.role(steps.role("bench", "review"))
    # a mixed team (frontier plans, light executes) splits the build into per-method subtasks
    mixed = isinstance(llm, Team) and llm.mixed and not resuming

    def tell(**kw):
        log.update(kw)
        if progress:
            progress({"stage": log["stage"], "round": log["round"], "jobs": jobs(workdir),
                      "sessions": log["sessions"][-8:], "qa": log["qa"], "minutes": round((time.time() - t0) / 60, 1),
                      **({"delegate": log["delegate"]} if log.get("delegate") else {})})

    def left() -> int | None:
        return None if deadline is None else max(60, int(deadline - time.time()) + 900)

    def session(p: str, why: str) -> dict:
        tell(stage=why)
        meta = worker.build(p, workdir, timeout=left())
        cost[0] += meta.get("cost_usd") or 0
        log["sessions"].append({"why": why, "llm": meta.get("llm"), "model": meta.get("model"),
                                "minutes": round((meta.get("ms") or 0) / 60000, 1),
                                "cost_usd": meta.get("cost_usd"), "text": (meta.get("text") or "")[-600:]})
        tell()
        return meta

    def wait_jobs(before: dict) -> list[dict]:
        """Block until a job that was running finishes (pausing hot GPU jobs), so dependent work can start."""
        while True:
            gpu_guard(workdir)
            js = jobs(workdir)
            if any(before.get(j["id"]) in ("running", "paused") and j["state"] not in ("running", "paused")
                   for j in js) or not any(j["state"] in ("running", "paused") for j in js):
                return js
            if deadline and time.time() > deadline:
                stop_jobs(workdir)
                return jobs(workdir)
            tell(stage="waiting for simulations")
            time.sleep(poll)

    def settle(meta: dict, max_resumes: int = 200) -> dict:
        """Resume the builder whenever one of its jobs finishes, until it ends a turn with nothing running."""
        for _ in range(max_resumes):
            before = {j["id"]: j["state"] for j in jobs(workdir)}
            if not any(v in ("running", "paused") for v in before.values()):
                return meta
            js = wait_jobs(before)
            done = [f"{j['id']}: {j['state']} after {j['minutes']} min (last log line: {j['tail']})"
                    for j in js if before.get(j["id"]) in ("running", "paused")
                    and j["state"] not in ("running", "paused")]
            still = [j["id"] for j in js if j["state"] in ("running", "paused")]
            if still:
                done.append("Still running: " + ", ".join(still) + ". Start whatever these results unblock "
                            "(and keep the allowed GPUs busy), then end your turn again.")
            late = " The time budget is over: unfinished jobs were stopped; use what finished." if (
                deadline and time.time() > deadline) else ""
            meta = session(RESUME.format(reason="These jobs have finished:\n" + "\n".join(done) + late),
                           "continuing after the jobs finished")
        return meta

    if mixed:
        tell(stage="splitting the build into subtasks")
        d = delegate(llm, goal=goal + "\nApproved stack:\n" + (st or "- a mechanistic model fitted to the "
                                                               "training data") + chain_text(chain),
                     context=prompt, workdir=workdir, n_max=4, timeout=left(),
                     progress=lambda: tell(stage="running the subtasks"))
        log["delegate"] = d
        cost[0] += d.get("cost_usd") or 0
        meta = session(prompt + "\n\n" + ASSEMBLE.format(delegate=_delegate_text(d)),
                       "assembling model.py from the subtasks")
    else:
        meta = session(RESUME.format(reason="You were interrupted (server restart); check the jobs and continue.")
                       if resuming else prompt, "building")
    meta = settle(meta)
    check = verify(workdir)
    for _ in range(2):
        if check["ok"]:
            break
        meta = settle(session(RESUME.format(reason="check_model.py fails:\n" + check["out"][-1200:]),
                              "fixing the contract check"))
        check = verify(workdir)
    held_titles = "; ".join(x["title"] for x in studies if x["id"] in held) or "none"
    for rnd in range(1, qa_rounds + 1 if check["ok"] else 1):
        log["round"] = rnd
        prev = "" if not log["qa"] else ("\nThis is review round %d. Your previous review asked for these fixes "
                                         "(see QA.md); check whether they were done properly:\n%s" % (
                                             rnd, _fix_text(log["qa"][-1])))
        tell(stage="QA review")
        r = reviewer.build(REVIEW.format(held=held_titles, knobs=json.dumps(problem["knobs"]), previous=prev),
                           workdir, timeout=None if not deadline else left(), schema=QA_SCHEMA,
                           tools="Bash,Read,Write,Glob,Grep,WebSearch,WebFetch")
        cost[0] += r.get("cost_usd") or 0
        qa = r.get("data") or {"overall": "fail", "summary": "the reviewer returned nothing", "methods": [],
                               "model": {"verdict": "fail", "issues": []}}
        log["qa"].append({"round": rnd, "llm": r.get("llm"), **qa})
        (workdir / "qa.json").write_text(json.dumps(log["qa"], indent=1))
        tell()
        if qa["overall"] != "fix" or rnd == qa_rounds or (deadline and time.time() > deadline):
            break
        (workdir / "QA.md").write_text(f"# QA review, round {rnd}\n\n{qa['summary']}\n\n{_fix_text(qa)}\n")
        meta = settle(session(RESUME.format(reason="The QA reviewer asked for fixes (also in QA.md). Do them, "
                                            "rerun what is needed, update report.json and model.py:\n"
                                            + _fix_text(qa)), f"applying QA fixes (round {rnd})"))
        check = verify(workdir)
        if not check["ok"]:
            meta = settle(session(RESUME.format(reason="check_model.py fails:\n" + check["out"][-1200:]),
                                  "fixing the contract check"))
            check = verify(workdir)
    report = {}
    if (workdir / "report.json").is_file():
        try:
            report = json.loads((workdir / "report.json").read_text())
        except json.JSONDecodeError:
            report = {"model": "report.json is not valid JSON"}
    last = log["qa"][-1] if log["qa"] else None
    return {"path": str(workdir / "model.py"), "check": check, "report": report,
            "summary": (meta.get("text") or "")[-2000:], "cost_usd": round(cost[0], 3),
            "seconds": round(time.time() - t0, 1), "qa": last, "qa_rounds": len(log["qa"]),
            "sessions": log["sessions"], "jobs": jobs(workdir), "delegate": log.get("delegate")}


def _fix_text(qa: dict) -> str:
    lines = [f"- [{m['id']}] {f}" for m in qa.get("methods", []) for f in m.get("fixes", [])]
    lines += [f"- [model] {i}" for i in (qa.get("model") or {}).get("issues", []) if qa["model"]["verdict"] != "pass"]
    return "\n".join(lines) or "(no specific fixes listed)"


def verify(workdir: Path) -> dict:
    if not (workdir / "model.py").is_file():
        return {"ok": False, "out": "no model.py was written"}
    r = subprocess.run([sys.executable, "check_model.py"], cwd=workdir, capture_output=True, text=True, timeout=300)
    out = (r.stdout + r.stderr).strip()[-1500:]
    return {"ok": r.returncode == 0 and "OK" in r.stdout, "out": out}
