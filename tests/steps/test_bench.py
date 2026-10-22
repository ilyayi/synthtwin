"""The bench step: the builder path for any other system (build, QA, blind
benchmark) and the builder agent's own behaviour (detached jobs, resumes,
tool policy)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from synthtwin.core import engine
from synthtwin.core.llm import Stub, _minimal

EXAMPLES = Path(__file__).parent.parent.parent / "examples"


# ---------------------------------------------------------------- any other system: the builder path
FILM_GOAL = {"system": "other", "material": "polyimide film", "method": "slot-die coating", "title": "PI film 20 um",
             "targets": [{"quantity": "film_thickness_um", "aim": "equal", "value": 20.0}],
             "knobs": [{"key": "coating_gap_um", "lo": 50.0, "hi": 300.0},
                       {"key": "solids_wt_pct", "lo": 10.0, "hi": 20.0}],
             "fixed": [{"key": "anneal_T_C", "value": 350.0}]}
BUILD_PROMPTS: list[str] = []


def film_llm(system: str, prompt: str, schema: dict) -> dict:
    ans = _minimal(schema)
    ans.update(reply="ok", ready=True)
    props = schema.get("properties", {})
    if "problem" in props:
        ans["problem"] = FILM_GOAL
    if "studies" in props:
        ans["studies"] = [{"title": t, "url": f"https://example.org/{t[:5]}", "year": "2022",
                           "material": "polyimide film", "method": "slot-die coating", "swept_key": "coating_gap_um",
                           "fixed": [{"key": "solids_wt_pct", "value": 15}],
                           "points": [{"swept_value": g, "outcomes": [{"quantity": "film_thickness_um", "value": k * g}]}
                                      for g in (50, 100, 200, 300)],
                           "takeaway": "thicker with gap", "confidence": "high"}
                          for t, k in (("Train gap sweep", 0.1), ("Held gap sweep", 0.131))]
    if "methods" in props and props["methods"]["items"].get("required", [None])[0] == "id" \
            and "tool" in props["methods"]["items"]["properties"]:
        ans["methods"] = [{"id": "wet_film", "name": "Wet-film mass balance", "tool": "python", "role": "h = c*gap*phi",
                           "feeds": "film_thickness_um", "est_min": 1, "selected": True, "insight": "gap sets h"},
                          {"id": "md_shrink", "name": "MD imidisation shrinkage", "tool": "lammps", "role": "density",
                           "feeds": "shrink factor", "est_min": 600, "selected": False, "insight": "too slow"}]
    if "insights" in props:
        ans["insights"] = ["gap matters most"]
    if "recipe" in props:
        ans["recipe"] = {"title": "R", "why": "w", "steps": ["1. coat"], "expected": "20 um", "checks": ["c"],
                         "risks": ["r"]}
    return ans


MODEL = '''
QUANTITIES = {"film_thickness_um": "um"}
def _h(c, k):
    return k * c["coating_gap_um"] * c.get("solids_wt_pct", 15) / 15
def predict(p):
    v = _h(p["conditions"], (p.get("calibration") or {}).get("k", 0.1))
    return {"film_thickness_um": {"value": v, "low": 0.9 * v, "high": 1.1 * v, "unit": "um"}}
def calibrate(p, outs):
    return {"k": outs[0]["value"] / _h(p["conditions"], 1.0)}
'''


def film_builder(prompt: str, cwd: Path) -> dict:
    BUILD_PROMPTS.append(prompt)
    (cwd / "model.py").write_text(MODEL)
    (cwd / "report.json").write_text(json.dumps({"methods": [{"id": "wet_film", "status": "ran"}], "model": "h=k*gap"}))
    return {"text": "built a mass-balance model", "cost_usd": 0.0}


def test_other_system_builds_and_runs(tmp_path: Path, settle) -> None:
    cfg = engine.AgentConfig(tmp_path / "data", EXAMPLES / "recipes.jsonl", EXAMPLES / "robot.yaml", None,
                             n_eval=12, llm=Stub(film_llm, builder=film_builder), workers=1)
    a = engine.Agent(cfg)
    sid = a.create("slot-die polyimide films of 20 um")["id"]
    s = settle(a, sid)
    assert s["problem"]["system"] == "other" and not s["phases"]["goal"]["errors"]
    a.confirm(sid, {"phase": "goal"})
    s = settle(a, sid)
    assert s["problem"]["fixed"] == {"anneal_T_C": 350.0}            # no colloid defaults
    studies = s["phases"]["prior"]["studies"]
    held = next(x["id"] for x in studies if x["title"].startswith("Held"))
    a.confirm(sid, {})
    s = settle(a, sid)
    M = s["phases"]["stack"]["methods"]
    assert [m["id"] for m in M if m["selected"]] == ["wet_film"] and s["phases"]["stack"]["estimate"]["now_s"] == 60
    a.confirm(sid, {})
    s = settle(a, sid)
    assert s["phase"] == "sample"
    a.confirm(sid, {"selected": [held]})
    s = settle(a, sid)
    B = s["phases"]["bench"]
    assert B["build"]["check"]["ok"], B["build"]
    # the builder saw the held-out study's anchor only, never its other outcomes
    assert "39.3" not in BUILD_PROMPTS[-1] and "26.2" not in BUILD_PROMPTS[-1] and "13.1" in BUILD_PROMPTS[-1]
    assert B["summary"]["n_scored"] == 1 and B["variant"] == "calibrated", B["summary"]
    a.confirm(sid, {})
    s = settle(a, sid)
    C = s["phases"]["case"]
    assert s["phase"] == "recipe" and C["tornado"][0]["knob"] in ("coating_gap_um", "solids_wt_pct")
    best = C["proposals"][0]
    assert abs(best["predicted"]["film_thickness_um"]["value"] - 20) < 1.5, best
    a.confirm(sid, {})
    s = settle(a, sid)
    assert s["phase"] == "robot"


def test_builder_waits_for_jobs_and_runs_qa(tmp_path: Path) -> None:
    """Long jobs run detached via simjob.py; the builder is resumed after them; QA fixes loop back."""
    from synthtwin.steps.bench import builder
    calls: list[str] = []

    def build_fn(prompt: str, cwd: Path) -> dict:
        calls.append(prompt)
        if len(calls) == 1:   # launch a "simulation" and end the turn
            subprocess.run([sys.executable, "simjob.py", "start", "md1", "--", "sleep 0.5; echo density 1.42"],
                           cwd=cwd, check=True)
            return {"text": "launched md1"}
        (cwd / "model.py").write_text(MODEL)
        (cwd / "report.json").write_text(json.dumps({"methods": [{"id": "md1", "status": "ran"}], "model": "m"}))
        return {"text": "assembled"}

    reviews: list[str] = []

    def review_fn(prompt: str, cwd: Path) -> dict:
        reviews.append(prompt)
        ok = len(reviews) > 1
        return {"overall": "pass" if ok else "fix", "summary": "s",
                "methods": [{"id": "md1", "verdict": "pass" if ok else "fix",
                             "checks": [{"name": "equilibrated", "ok": ok, "evidence": "log"}],
                             "fixes": [] if ok else ["discard the first 20% as equilibration"]}],
                "model": {"verdict": "pass", "issues": []}}

    seen: list[dict] = []
    pb = {"material": "x", "method": "y", "targets": {"film_thickness_um": {"value": 20}},
          "knobs": {"coating_gap_um": [50, 300], "solids_wt_pct": [10, 20]}, "fixed": {}}
    out = builder.build(Stub(builder=build_fn, reviewer=review_fn), tmp_path / "w", pb, [], [], set(), None,
                        qa_rounds=3, progress=seen.append, poll=0.1)
    assert "md1: done" in calls[1] and "density 1.42" in calls[1]
    assert "discard the first 20%" in calls[2] and (tmp_path / "w" / "QA.md").is_file()
    assert out["check"]["ok"] and out["qa"]["overall"] == "pass" and out["qa_rounds"] == 2
    assert "previous review" in reviews[1]
    assert any(p["stage"] == "waiting for simulations" for p in seen)
    assert out["jobs"][0]["state"] == "done"


def test_builder_resumes_when_any_job_finishes(tmp_path: Path) -> None:
    """A finished prerequisite (e.g. charges) wakes the builder while long jobs keep running."""
    from synthtwin.steps.bench import builder
    calls: list[str] = []

    def build_fn(prompt: str, cwd: Path) -> dict:
        calls.append(prompt)
        if len(calls) == 1:
            for jid, cmd in (("prep", "sleep 0.2"), ("long", "sleep 3")):
                subprocess.run([sys.executable, "simjob.py", "start", jid, "--", cmd], cwd=cwd, check=True)
            return {"text": "launched"}
        if len(calls) == 2:
            subprocess.run([sys.executable, "simjob.py", "start", "md", "--", "sleep 0.2"], cwd=cwd, check=True)
            return {"text": "started md"}
        (cwd / "model.py").write_text(MODEL)
        return {"text": "assembled"}
    pb = {"material": "x", "method": "y", "targets": {"film_thickness_um": {"value": 20}},
          "knobs": {"coating_gap_um": [50, 300], "solids_wt_pct": [10, 20]}, "fixed": {}}
    out = builder.build(Stub(builder=build_fn), tmp_path / "w", pb, [], [], set(), None, qa_rounds=0, poll=0.05)
    assert "prep: done" in calls[1] and "Still running: long" in calls[1] and "long:" not in calls[1]
    assert out["check"]["ok"] and {j["id"] for j in out["jobs"]} == {"prep", "long", "md"}
    assert all(j["state"] == "done" for j in out["jobs"])


def test_simjob_keeps_quoting_and_records_syntax_errors(tmp_path: Path) -> None:
    from synthtwin.steps.bench import builder
    (tmp_path / "simjob.py").write_text(builder.SIMJOB)

    def run(jid: str, *words: str) -> str:
        subprocess.run([sys.executable, "simjob.py", "start", jid, "--", *words], cwd=tmp_path, check=True)
        for _ in range(100):
            if (tmp_path / "jobs" / jid / "rc").exists():
                break
            time.sleep(0.05)
        return (tmp_path / "jobs" / jid / "rc").read_text().strip()
    assert run("loop", "bash", "-c", "for i in 1 2; do echo x$i; done") == "0"
    assert "x2" in (tmp_path / "jobs" / "loop" / "log").read_text()
    assert run("str", "cd jobs && ls loop > /dev/null") == "0"
    assert run("bad", "while true; do") == "2"


def test_toolbox_policy_and_registry(tmp_path: Path) -> None:
    from synthtwin.steps.bench import builder
    from synthtwin.core import toolbox
    box = toolbox.ensure(tmp_path / "tools")
    bad = subprocess.run([sys.executable, "register.py", "--name", "x", "--use", "u", "--run", "r", "--check", "false"],
                         cwd=box, capture_output=True, text=True)
    assert bad.returncode and not toolbox.registry(box)
    subprocess.run([sys.executable, "register.py", "--name", "cantera", "--use", "reaction kinetics",
                    "--run", "envs/sim/bin/python x.py", "--check", "true", "--version", "3.1"], cwd=box, check=True)
    assert toolbox.registry(box)[0]["name"] == "cantera"
    assert "cantera 3.1 (tool area)" in toolbox.tools_text(None, box)
    seen: list[str] = []

    def build_fn(prompt: str, cwd: Path) -> dict:
        seen.append(prompt)
        (cwd / "model.py").write_text(MODEL)
        return {"text": "ok"}
    pb = {"material": "x", "method": "y", "targets": {"film_thickness_um": {"value": 20}},
          "knobs": {"coating_gap_um": [50, 300], "solids_wt_pct": [10, 20]}, "fixed": {}}
    builder.build(Stub(builder=build_fn), tmp_path / "w", pb, [], [], set(), None, qa_rounds=0, toolbox=box)
    assert "You MAY install" in seen[0] and str(box) in seen[0] and "cantera" in seen[0]
    builder.build(Stub(builder=build_fn), tmp_path / "w2", pb, [], [], set(), None, qa_rounds=0)
    assert "Do not install packages." in seen[-1]


