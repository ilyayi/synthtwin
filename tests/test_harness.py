"""The self-improving harness: identity injection, reflect's single lesson,
evolve's adopt and keep-base paths, rollback, the API endpoints and the engine
hooks (reflect after a confirm and after a robot result; prompts byte-identical
until a step has an overlay or lessons)."""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from synthtwin.core import engine, harness, runner
from synthtwin.core.llm import Stub
from synthtwin.core.runner import Config
from synthtwin.ui.server import App, make_handler

EXAMPLES = Path(__file__).parent.parent / "examples"
PROBLEM = {"material": "Au", "method": "citrate reduction", "targets": {"size_mean_nm": {"value": 15.0}},
           "knobs": {"ratio_reductant_precursor": [1.0, 10.0], "temperature_C": [60.0, 100.0]},
           "fixed": {"conc_precursor_mM": 0.25}}


def at_stack(agent: engine.Agent, sid: str = "hv-study") -> dict:
    """A recorded study resting at the stack step (what a probe replays on)."""
    s = engine.new_study(sid, "Au 15 nm by citrate")
    s["problem"] = dict(PROBLEM)
    s["phase"] = "stack"
    s["phases"]["stack"] = {"status": "awaiting_user",
                            "methods": [{"id": "continuum", "selected": True, "why": "", "insight": "predicts"}]}
    runner.save(agent.path(sid), s)
    return s


# ---------------------------------------------------------------- inject
def test_inject_is_identity_with_no_harness(tmp_path: Path) -> None:
    h = harness.Harness(tmp_path)
    assert h.inject("stack", "SYSTEM TEXT") == "SYSTEM TEXT"
    assert h.overlay("stack") == "" and h.version("stack") == 0


def test_inject_appends_overlay_and_ranks_lessons_by_cue(tmp_path: Path) -> None:
    h = harness.Harness(tmp_path)
    h.save_overlay("stack", "Cap temperature knobs at the robot's limit.")
    h.append_lesson("stack", {"cue": "temperature knob proposed above the robot limit",
                              "lesson": "clip ranges to STATE.robot first", "evidence": "x", "study": "s-1"})
    for i in range(6):      # six more, cue-matched nowhere: only 5 lessons inject, this one last
        h.append_lesson("stack", {"cue": f"unrelated cue {i}", "lesson": f"noise {i}"})
    out = h.inject("stack", "SYSTEM", {"problem": PROBLEM, "knobs": ["temperature_C"]})
    assert out.startswith("SYSTEM") and "## Harness for this step" in out
    assert "Cap temperature knobs" in out
    assert out.count("- ") <= harness.MAX_LESSONS            # <= 5 lessons
    assert out.index("temperature knob") < out.index("unrelated cue")   # the cue match leads
    assert h.inject("goal", "SYSTEM") == "SYSTEM"            # other steps stay untouched


# ---------------------------------------------------------------- reflect
def test_reflect_writes_at_most_one_lesson(tmp_path: Path) -> None:
    h = harness.Harness(tmp_path)
    llm = Stub(lambda sys_, prompt, schema: {
        "rows": [{"component": "overlay", "verdict": "confounded", "note": "one study only"},
                 {"component": "bogus", "verdict": "not a verdict"}],
        "lesson": {"cue": "the stack proposes ranges the robot cannot reach",
                   "lesson": "clip every knob to the robot's limits before naming a range",
                   "evidence": "hv-1 stack: proposed 110 C, robot caps at 100 C", "confidence": "medium"}})
    row = harness.reflect(llm, h, "stack", {"study": "hv-1", "step": "stack"})
    assert row["rows"] == [{"component": "overlay", "verdict": "confounded", "note": "one study only"}]
    assert row["lesson"] == "l1"
    lessons = h.lessons("stack")
    assert len(lessons) == 1 and lessons[0]["study"] == "hv-1" and lessons[0]["verdict"] == "confounded"
    # a second reflect with nothing to say: a ledger row, no new lesson
    row2 = harness.reflect(Stub(lambda s, p, sc: {"rows": []}), h, "stack", {"study": "hv-2"})
    assert "lesson" not in row2 and len(h.lessons("stack")) == 1
    assert len(h.ledger("stack")) == 2 and h.ledger("stack")[0]["kind"] == "reflect"


def test_reflect_drops_empty_lesson(tmp_path: Path) -> None:
    h = harness.Harness(tmp_path)
    row = harness.reflect(Stub(lambda s, p, sc: {"rows": [], "lesson": {"cue": "", "lesson": ""}}),
                          h, "bench", {"study": "x"})
    assert "lesson" not in row and h.lessons("bench") == []


# ---------------------------------------------------------------- evolve
PLAN_ADOPT = lambda sys_, prompt, schema: (
    {"inv": {"action": "EDIT", "overlay": "Clip every knob range to the robot's limits before naming it.",
             "moment": "the agent proposed a temperature range past the robot's 100 C cap",
             "evidence": "repeated failure", "component": "overlay"},
     "dom": {"action": "KEEP_BASE", "overlay": "", "moment": "", "component": ""}}
    if "inv" in schema.get("properties", {}) else
    {"decision": "adopt", "choice": "inv", "reason": "INV delivers on both replays; DOM was KEEP_BASE.",
     "checks": {c: "ok" for c in harness.CHECKS}})


def test_evolve_adopts_after_probing(agent: engine.Agent) -> None:
    s = at_stack(agent)
    h = harness.Harness(agent.cfg.data_dir)
    seen: list[str] = []
    work = Stub(lambda sys_, prompt, schema: (seen.append(sys_), {"reply": "Here is the stack…", "ready": True})[1])
    row = harness.evolve(agent, Stub(PLAN_ADOPT), work, "stack", studies=[s], k=2, h=h)
    # probed base and INV on the study (DOM was KEEP_BASE), then adopted and versioned
    assert row["probes"] and set(row["probes"][0]["arms"]) == {"base", "inv"}
    assert len(seen) == 2 and any("Clip every knob range" in x for x in seen)   # the candidate prompt
    assert all(x.startswith(seen[0].split("## Harness")[0]) for x in seen)      # same stored prompt otherwise
    assert row["composer"]["decision"] == "adopt" and row["overlay_version"] == 1
    assert h.version("stack") == 1 and "Clip every knob range" in h.overlay("stack")
    assert [c for c in h.experience("stack") if c["kind"] == "change"]          # EXPERIENCE row
    assert h.ledger("stack")[-1]["kind"] == "evolve"
    assert row["candidates"]["dom"]["action"] == "KEEP_BASE"


def test_evolve_keeps_base_when_no_candidate(agent: engine.Agent) -> None:
    s = at_stack(agent)
    h = harness.Harness(agent.cfg.data_dir)
    keep = lambda sys_, prompt, schema: {"inv": {"action": "KEEP_BASE", "overlay": "", "moment": "", "component": ""},
                                         "dom": {"action": "KEEP_BASE", "overlay": "", "moment": "", "component": ""}}
    work = Stub(lambda sys_, prompt, schema: (_ for _ in ()).throw(AssertionError("no work without a candidate")))
    row = harness.evolve(agent, Stub(keep), work, "stack", studies=[s], k=2, h=h)
    assert row["composer"]["decision"] == "keep_base" and row["probes"] == []
    assert h.version("stack") == 0 and h.overlay("stack") == ""
    agent.mutate(s["id"], lambda x: x.update(phase="goal", phases={p: {"status": "pending"} for p in engine.ORDER}))
    with pytest.raises(ValueError):                        # nothing to replay on
        harness.evolve(agent, Stub(keep), work, "goal", studies=[agent.load(s["id"])], h=h)


# ---------------------------------------------------------------- rollback
def test_rollback_restores_an_earlier_version(tmp_path: Path) -> None:
    h = harness.Harness(tmp_path)
    h.save_overlay("stack", "first overlay")
    h.save_overlay("stack", "second overlay")
    assert h.overlay("stack") == "second overlay"
    r = h.rollback("stack", 1)
    assert r["version"] == 1 and h.overlay("stack") == "first overlay" and h.version("stack") == 1
    assert h.save_overlay("stack", "third") == 3            # versions are never reused
    with pytest.raises(ValueError):
        h.rollback("stack", 99)


# ---------------------------------------------------------------- engine hooks
def test_confirm_reflects_in_background(agent: engine.Agent, settle) -> None:
    sid = agent.create("I need ~15 nm citrate gold for a DLS standard")["id"]
    settle(agent, sid)
    agent.confirm(sid, {"phase": "goal"})
    ledger = agent.cfg.data_dir / "harness" / "goal" / "ledger.jsonl"
    for _ in range(100):                                    # the reflect thread, never blocking the step
        if ledger.is_file():
            break
        time.sleep(0.1)
    rows = [json.loads(x) for x in ledger.read_text().splitlines()]
    assert rows and rows[0]["kind"] == "reflect" and rows[0]["study"] == sid
    notes = agent.load(sid)["phases"]["goal"].get("notes") or []    # no reflect failure was noted
    assert not any("harness reflect failed" in str(n) for n in notes)


def test_turn_injects_only_when_a_step_has_a_harness(agent: engine.Agent, settle) -> None:
    sid = at_stack(agent)["id"]
    s = agent.load(sid)
    key, system, prompt, ctx = agent.turn_parts(s)
    assert agent.harness().inject("stack", system, ctx) == system   # nothing stored: byte-identical
    agent.harness().save_overlay("stack", "Always give est_min for every method.")
    out = agent.harness().inject("stack", system, ctx)
    assert out.startswith(system) and "## Harness for this step" in out and "est_min" in out
    assert agent.harness().inject("goal", system, ctx) == system    # the other steps stay clean


def test_robot_result_reflects(agent: engine.Agent, settle) -> None:
    s = engine.new_study("hv-robot", "Au 15 nm by citrate")
    s["problem"] = dict(PROBLEM)
    s["phase"] = "robot"
    s["phases"]["robot"] = {"status": "awaiting_user", "request": {"proposal": {
        "id": "p1", "method": "citrate reduction", "conditions": {},
        "predicted": {"size_mean_nm": {"value": 15, "low": 12, "high": 18, "unit": "nm"}}}}}
    runner.save(agent.path("hv-robot"), s)
    agent.result("hv-robot", {"measured": {"size_mean_nm": 15.2}})
    assert agent.load("hv-robot")["phases"]["robot"]["results"][0]["inside"] is True
    ledger = agent.cfg.data_dir / "harness" / "robot" / "ledger.jsonl"
    for _ in range(100):
        if ledger.is_file():
            break
        time.sleep(0.1)
    assert json.loads(ledger.read_text().splitlines()[0])["trigger"] == "robot result"


# ---------------------------------------------------------------- API
@pytest.fixture()
def hvbase(tmp_path: Path):
    cfg = engine.AgentConfig(tmp_path / "data", EXAMPLES / "recipes.jsonl", EXAMPLES / "robot.yaml",
                             n_eval=12, predictor="np_stub", llm=Stub())
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(cfg)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", cfg
    srv.shutdown()


def call(url: str, body: dict | None = None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_harness_api(hvbase) -> None:
    url, cfg = hvbase
    agent = engine.Agent(cfg)                       # a recorded study to probe on
    at_stack(agent)
    code, lst = call(url + "/api/harness")
    assert code == 200 and [s["step"] for s in lst["steps"]] == engine.ORDER
    st = {s["step"]: s for s in lst["steps"]}
    assert st["stack"]["protocol_version"] and st["stack"]["overlay_version"] == 0 and st["stack"]["lessons"] == 0
    code, d = call(url + "/api/harness/stack")
    assert code == 200 and d["overlay"] == "" and d["history"] == [] and d["ledger"] == []
    assert call(url + "/api/harness/nope")[0] == 404

    code, job = call(url + "/api/harness/stack/evolve", {})          # stub proposes KEEP_BASE both
    assert code == 202 and job["status"] == "running"
    for _ in range(100):
        _, cur = call(url + f"/api/harness/stack/evolve?id={job['id']}")
        if cur["job"]["status"] != "running":
            break
        time.sleep(0.1)
    assert cur["job"]["status"] == "done"
    assert cur["job"]["result"]["composer"]["decision"] == "keep_base"
    _, d = call(url + "/api/harness/stack")
    assert d["last_evolve"]["decision"] == "keep_base" and d["overlay_version"] == 0

    h = harness.Harness(cfg.data_dir)                                # seed versions, roll back over the API
    h.save_overlay("stack", "v1 text")
    h.save_overlay("stack", "v2 text")
    assert call(url + "/api/harness/stack/rollback", {"version": 1})[0] == 200
    _, d = call(url + "/api/harness/stack")
    assert d["overlay_version"] == 1 and d["overlay"] == "v1 text"
    assert call(url + "/api/harness/stack/rollback", {"version": 9})[0] == 400
    assert call(url + "/api/harness/stack/rollback", {})[0] == 400


def test_harness_api_needs_the_agent(tmp_path: Path) -> None:
    cfg = Config(tmp_path / "data", EXAMPLES / "recipes.jsonl", EXAMPLES / "robot.yaml",
                 n_eval=4, predictor="np_stub")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(cfg)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert call(f"http://127.0.0.1:{srv.server_address[1]}/api/harness/stack/evolve", {})[0] == 400
    finally:
        srv.shutdown()
