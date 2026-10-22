"""Model backends and the mix: the registry (built-ins + models.yaml), availability
checks, Team routing per step.json, the plan-delegates-to-workers pattern, and the
/api/models endpoints. All stub-backed; no real model is called."""
from __future__ import annotations

import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from synthtwin import steps
from synthtwin.core import engine, llm
from synthtwin.core.llm import Stub, _minimal
from synthtwin.core.team import SPLIT_SCHEMA, REVIEW_SCHEMA, Team, delegate

EXAMPLES = Path(__file__).parent.parent / "examples"


# ---------------------------------------------------------------- registry
def write_models(d: Path, backends: dict) -> Path:
    p = d / "models.yaml"
    p.write_text(yaml.safe_dump({"backends": backends}))
    return p


def test_registry_builtin_and_yaml(tmp_path: Path, monkeypatch) -> None:
    reg = llm.load_backends()
    assert reg["claude"]["cmd"] == ["claude"] and reg["stub"]["cmd"] == []
    p = write_models(tmp_path, {"glm": {"cmd": ["glm", "--cloud"], "label": "GLM", "kind": "frontier"}})
    reg = llm.load_backends(p)
    assert reg["glm"] == {"cmd": ["glm", "--cloud"], "label": "GLM", "kind": "frontier", "model": "opus"}
    assert "claude" in reg                                       # the built-ins stay
    monkeypatch.setenv("SYNTHTWIN_MODELS", str(p))               # the env picks the file, too
    assert "glm" in llm.load_backends()
    bad = tmp_path / "bad.yaml"
    bad.write_text("backends: {x: {model: opus}}")               # no cmd
    with pytest.raises(ValueError, match="needs a cmd list"):
        llm.load_backends(bad)


def test_make_builds_named_backends(tmp_path: Path, monkeypatch) -> None:
    p = write_models(tmp_path, {"glm": {"cmd": ["glm", "--cloud"], "model": "glm-4", "label": "GLM",
                                        "kind": "frontier"}})
    c = llm.make("glm", path=p)
    assert c.cmd == ["glm", "--cloud"] and c.name == "glm" and c.model == "glm-4" and c.label == "GLM"
    assert isinstance(c, llm.ClaudeCLI) and c.role("work") is c
    assert llm.make("stub", path=p).__class__ is Stub
    with pytest.raises(ValueError, match="unknown LLM backend"):
        llm.make("nope", path=p)
    calls = []

    class R:
        returncode, stderr = 0, ""
        stdout = json.dumps({"structured_output": {"reply": "x"}})

    monkeypatch.setattr(llm.subprocess, "run", lambda cmd, **kw: (calls.append(cmd), R())[1])
    c.ask("s", "p", {"type": "object", "properties": {"reply": {"type": "string"}},
                     "required": ["reply"]})
    assert calls[-1][:2] == ["glm", "--cloud"]                   # the prefix replaces `claude`
    assert "--json-schema" in calls[-1]
    assert llm.ClaudeCLI(binary="claude").cmd == ["claude"]       # binary= still works


def test_availability(tmp_path: Path) -> None:
    assert llm.available({"cmd": []}) == (True, "")               # stub: always there
    assert llm.available({"cmd": ["definitely-not-on-path-xyz"]})[0] is False
    assert llm.available({"cmd": ["x"], "check": "exit 0"}) == (True, "")
    ok, why = llm.available({"cmd": ["x"], "check": "exit 3"})
    assert not ok and why
    ok, _ = llm.available({"cmd": ["x"], "check": "sleep 5"}, timeout=0.2)   # a check that never answers
    assert not ok


def test_availability_url(tmp_path: Path) -> None:
    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            if self.path == "/v1/models":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"data": []}')
            else:
                self.send_error(404)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    up = f"http://127.0.0.1:{srv.server_address[1]}/v1/models"
    try:
        assert llm.available({"cmd": ["x"], "check": {"url": up}})[0] is True
        assert llm.available({"cmd": ["x"], "check": up})[0] is True            # a bare URL string
        assert llm.available({"cmd": ["x"], "check": {"url": up + "/nope"}})[0] is True   # answered = up
        assert llm.available({"cmd": ["x"], "check": {"url": "http://127.0.0.1:1/x"}})[0] is False
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- routing
def test_step_models_routing() -> None:
    """Every step.json declares its models map; it agrees with the defaults it means to override."""
    for sid in steps.ORDER:
        assert steps.role(sid, "turn") == "plan", sid             # agent turns are frontier work
    assert steps.role("bench", "build") == "work" and steps.role("bench", "review") == "plan"
    assert steps.role("prior", "lit") == "work" and steps.role("prior", "triage") == "work"
    assert steps.role("robot", "materials") == "work"
    assert steps.role("goal", "build") == "work"                  # not in goal's map: the default
    with pytest.raises(KeyError):
        steps.role("goal", "nope")


def _named(name: str, fn=None) -> Stub:
    s = Stub(fn)
    s.name = name
    return s


def test_team_routes_and_meta() -> None:
    seen: list[str] = []

    def plan_fn(system: str, prompt: str, schema: dict) -> dict:
        seen.append("plan:" + prompt[:6])
        return _minimal(schema)

    def work_fn(system: str, prompt: str, schema: dict) -> dict:
        seen.append("work:" + prompt[:6])
        return _minimal(schema)

    t = Team(_named("front", plan_fn), _named("light", work_fn))
    assert t.mixed and t.name == "front/light"
    t.ask("s", "hello ", {"type": "object"})
    assert seen == ["plan:hello "]
    assert t.role("work").ask("s", "job ", {"type": "object"})["_meta"]["llm"] == "light"
    assert seen[-1] == "work:job "
    a = t.ask("s", "x", {"type": "object"})
    assert a["_meta"] == {"cost_usd": 0, "ms": 0, "llm": "front", "model": "front", "role": "plan"}
    assert t.role("work").ask("s", "x", {"type": "object"})["_meta"]["role"] == "work"
    built = {"calls": []}

    def build_fn(prompt: str, cwd: Path) -> dict:
        built["calls"].append(prompt)
        return {"text": "done"}

    w = Stub(builder=build_fn)
    w.name = "light"
    t2 = Team(Stub(), w)
    r = t2.build("p", Path("/tmp"), None)
    assert built["calls"] == ["p"] and r["llm"] == "light" and r["role"] == "work"


def test_single_backend_answers_role() -> None:
    s = Stub()
    assert s.role("work") is s and s.role("plan") is s
    c = llm.ClaudeCLI()
    assert c.role("work") is c
    assert llm.make_team("stub", None).__class__ is Stub      # same name twice: one backend
    assert llm.make_team("stub", "stub").__class__ is Stub


def test_make_team_mixes(tmp_path: Path) -> None:
    p = write_models(tmp_path, {"local": {"cmd": ["glm", "--local"], "kind": "light", "label": "Local"}})
    t = llm.make_team("claude", "local", path=p)
    assert isinstance(t, Team) and t.plan.name == "claude" and t.work.name == "local"
    assert t.work.cmd == ["glm", "--local"] and t.work.kind == "light"


# ---------------------------------------------------------------- delegate
def _team_for_delegate(tmp_path: Path, fixes_first_round: bool):
    """plan stub splits into two subtasks, then accepts (or fixes the second once);
    the work stub writes the file only when told to (or on its fix round)."""
    asks: list[dict] = []
    builds: list[Path] = []

    def plan_fn(system: str, prompt: str, schema: dict) -> dict:
        asks.append({"system": system, "prompt": prompt})
        if schema is SPLIT_SCHEMA:
            return {"subtasks": [
                {"title": "Mass balance", "instructions": "write k.txt saying k=0.1",
                 "files": ["k.txt"], "check": "test -f k.txt"},
                {"title": "Shrinkage", "instructions": "write s.txt",
                 "files": ["s.txt"], "check": "test -f s.txt"}]}
        if fixes_first_round:
            return {"reviews": [{"title": "Mass balance", "verdict": "accept"},
                                {"title": "Shrinkage", "verdict": "fix",
                                 "instructions": "write s.txt after all"}]}
        return {"reviews": [{"title": t, "verdict": "accept"}
                            for t in ("Mass balance", "Shrinkage")]}

    def build_fn(prompt: str, cwd: Path) -> dict:
        builds.append(cwd)
        if "write k.txt" in prompt or "k=0.1" in prompt:
            (cwd / "k.txt").write_text("k=0.1")
        if "write s.txt" in prompt:
            (cwd / "s.txt").write_text("s")
        return {"text": "wrote the files"}

    plan, work = _named("front", plan_fn), _named("light")
    work.builder = build_fn
    return Team(plan, work), asks, builds


def test_delegate_accepts(tmp_path: Path) -> None:
    t, asks, builds = _team_for_delegate(tmp_path, fixes_first_round=False)
    d = delegate(t, "build a predictor", "the context", tmp_path / "w")
    assert len(d["subtasks"]) == 2 and d["fixed"] == []
    assert d["accepted"] == ["Mass balance", "Shrinkage"]
    assert {s["llm"] for s in d["subtasks"]} == {"light"}       # the workers, not the planner
    assert {s["model"] for s in d["subtasks"]} == {"light"}
    dirs = {s["dir"] for s in d["subtasks"]}
    assert dirs == {"01-mass-balance", "02-shrinkage"} and all(s["check"]["ok"] for s in d["subtasks"])
    assert all((tmp_path / "w" / dd).is_dir() for dd in dirs)
    assert "GOAL" in asks[0]["prompt"] and "the context" in asks[0]["prompt"]   # the split saw the job
    assert "Mass balance" in asks[1]["prompt"] and "FAILED" not in asks[1]["prompt"]  # the review saw results


def test_delegate_one_fix_round(tmp_path: Path) -> None:
    t, asks, builds = _team_for_delegate(tmp_path, fixes_first_round=True)
    # first work round "forgets" s.txt: only k.txt is written
    orig = t.work.builder

    def forgetful(prompt: str, cwd: Path) -> dict:
        if "YOUR SUBTASK: Shrinkage" in prompt and "fix" not in prompt.lower():
            return {"text": "did nothing"}                       # the review must catch this
        return orig(prompt, cwd)

    t.work.builder = forgetful
    d = delegate(t, "build a predictor", "", tmp_path / "w")
    shrink = next(s for s in d["subtasks"] if s["title"] == "Shrinkage")
    assert shrink["rounds"] == 2 and shrink["check"]["ok"]       # one fix round, then the check passes
    assert d["fixed"] == ["Shrinkage"] and d["accepted"] == ["Mass balance", "Shrinkage"]
    assert shrink["text"] == "wrote the files"


def test_delegate_needs_subtasks(tmp_path: Path) -> None:
    t = Team(_named("front", lambda s, p, schema: {"subtasks": []}), Stub())
    with pytest.raises(llm.LLMError, match="no subtasks"):
        delegate(t, "g", "", tmp_path / "w")


# ---------------------------------------------------------------- builder, mixed team
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


def test_builder_delegates_when_mixed(tmp_path: Path) -> None:
    """A mixed team splits the build: the plan model returns the subtasks, light workers write
    them in their own folders, one assembly session builds model.py, and QA still reviews."""
    from synthtwin.steps.bench import builder

    def plan_fn(system: str, prompt: str, schema: dict) -> dict:
        if schema is SPLIT_SCHEMA:
            return {"subtasks": [
                {"title": "Wet film balance", "instructions": "write wet.json",
                 "files": ["wet.json"], "check": "test -f wet.json"},
                {"title": "Drying curve", "instructions": "write dry.json",
                 "files": ["dry.json"], "check": "test -f dry.json"}]}
        return {"reviews": [{"title": t, "verdict": "accept"} for t in ("Wet film balance", "Drying curve")]}

    work_calls: list[str] = []

    def work_fn(prompt: str, cwd: Path) -> dict:
        work_calls.append(prompt)
        if "split into subtasks" in prompt:                      # the assembly session, in the workdir root
            (cwd / "model.py").write_text(MODEL)
            (cwd / "report.json").write_text(json.dumps(
                {"methods": [{"id": "wet_film", "status": "ran"}], "model": "h=k*gap"}))
            return {"text": "assembled model.py from the subtasks"}
        name = "wet.json" if "YOUR SUBTASK: Wet film" in prompt else "dry.json"
        (cwd / name).write_text("{}")
        return {"text": f"wrote {name}"}

    plan, work = _named("front", plan_fn), _named("light")
    work.builder = work_fn
    t = Team(plan, work)
    pb = {"material": "x", "method": "y", "targets": {"film_thickness_um": {"value": 20}},
          "knobs": {"coating_gap_um": [50, 300], "solids_wt_pct": [10, 20]}, "fixed": {}}
    seen: list[dict] = []
    out = builder.build(t, tmp_path / "w", pb, [{"id": "wet_film", "name": "Wet film", "tool": "python",
                                                 "selected": True}], [], set(), None,
                        qa_rounds=1, progress=seen.append, poll=0.05)
    assert out["check"]["ok"] and out["delegate"]["accepted"] == ["Wet film balance", "Drying curve"]
    assert (tmp_path / "w" / "01-wet-film-balance" / "wet.json").is_file()
    assert (tmp_path / "w" / "02-drying-curve" / "dry.json").is_file()
    assert any("01-wet-film-balance" in c for c in work_calls)   # workers were pointed at their folders
    assert any("subtasks" in p and p["stage"] == "running the subtasks" or p.get("delegate")
               for p in seen)                                   # the progress carried the delegate log
    assert out["sessions"][-1]["why"] == "assembling model.py from the subtasks"
    assert out["qa"]["overall"] == "pass"                        # QA reviewed (plan stub: default pass)


def test_builder_single_backend_never_delegates(tmp_path: Path) -> None:
    from synthtwin.steps.bench import builder

    def build_fn(prompt: str, cwd: Path) -> dict:
        (cwd / "model.py").write_text(MODEL)
        return {"text": "built it in one session"}

    pb = {"material": "x", "method": "y", "targets": {"film_thickness_um": {"value": 20}},
          "knobs": {"coating_gap_um": [50, 300], "solids_wt_pct": [10, 20]}, "fixed": {}}
    out = builder.build(Stub(builder=build_fn), tmp_path / "w", pb, [], [], set(), None, qa_rounds=0)
    assert out["check"]["ok"] and out["delegate"] is None
    assert not any(p.is_dir() for p in (tmp_path / "w").glob("0*"))


# ---------------------------------------------------------------- the API
@pytest.fixture()
def base(tmp_path: Path):
    p = write_models(tmp_path, {"glm": {"cmd": ["/bin/true"], "label": "GLM", "kind": "frontier"},
                                "local": {"cmd": ["/bin/true"], "label": "Local", "kind": "light",
                                          "check": "exit 0"}})
    cfg = engine.AgentConfig(tmp_path / "data", EXAMPLES / "recipes.jsonl", EXAMPLES / "robot.yaml",
                             n_eval=4, llm=Stub(), workers=1)
    from synthtwin.ui.server import App, make_handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(cfg, models=p)))
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


def test_models_api(base) -> None:
    url, cfg = base
    code, m = call(url + "/api/models")
    assert code == 200 and m["enabled"] and m["current"]
    names = {b["name"]: b for b in m["backends"]}
    assert set(names) == {"claude", "stub", "glm", "local"}
    assert names["local"]["available"] and names["glm"]["kind"] == "frontier"
    assert names["stub"]["available"]
    pres = {p["name"]: p for p in m["presets"]}
    assert pres["Claude plans · GLM executes"] == {"name": "Claude plans · GLM executes",
                                                   "plan": "claude", "work": "glm"}
    assert pres["GLM plans · local executes"]["work"] == "local"
    # switch the mix at runtime: no restart, the agent's next calls use it
    code, m = call(url + "/api/models", {"plan": "glm", "work": "local"})
    assert code == 200 and m["plan"] == "glm" and m["work"] == "local"
    assert isinstance(cfg.llm, Team) and cfg.llm.plan.name == "glm" and cfg.llm.work.name == "local"
    assert call(url + "/api/models", {"plan": "stub"})[1]["plan"] == "stub"   # work defaults to plan
    assert cfg.llm.__class__ is Stub
    assert call(url + "/api/models", {"plan": "nope"})[0] == 400
    # an unavailable backend is listed with its reason, and its presets switch off
    call(url + "/api/models", {"plan": "claude", "work": "claude"})
    code, m = call(url + "/api/models")
    assert all("reason" in b for b in m["backends"])


def test_models_api_agent_off(tmp_path: Path) -> None:
    from synthtwin.ui.server import App, make_handler
    cfg = engine.AgentConfig(tmp_path / "data", EXAMPLES / "recipes.jsonl", EXAMPLES / "robot.yaml",
                             n_eval=4, llm=None, workers=1)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(cfg, models=tmp_path / "none.yaml")))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        code, m = call(url + "/api/models")                 # the registry is still listed
        assert code == 200 and not m["enabled"] and not m["current"]
        assert {b["name"] for b in m["backends"]} == {"claude", "stub"}
        assert call(url + "/api/models", {"plan": "claude"})[0] == 400
    finally:
        srv.shutdown()
