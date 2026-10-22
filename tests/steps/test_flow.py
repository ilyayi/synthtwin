"""The whole pipeline end to end with a scripted LLM and the stub predictor:
goal -> related studies -> stack -> sample -> benchmark -> case -> recipe ->
robot (the fixtures live in tests/conftest.py)."""
from __future__ import annotations

import json

import pytest

from synthtwin.core import catalog, engine


def _download(agent: engine.Agent, sid: str) -> dict:
    """GET /api/agent/<sid>/package from a live server on the same data."""
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    from synthtwin.ui.server import App, make_handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(agent.cfg)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/api/agent/{sid}/package",
                                    timeout=10) as r:
            assert "attachment" in r.headers["Content-Disposition"]
            return json.loads(r.read())
    finally:
        srv.shutdown()


def test_full_flow(agent: engine.Agent, settle, prompts: list[str]) -> None:
    sid = agent.create("I need ~15 nm citrate gold for a DLS standard")["id"]
    s = settle(agent, sid)
    assert s["phase"] == "goal" and s["problem"]["targets"] == {"size_mean_nm": {"value": 15.0}}
    with pytest.raises(ValueError):
        agent.confirm(sid, {"phase": "stack"})

    agent.confirm(sid, {"phase": "goal"})
    s = settle(agent, sid)
    assert s["phase"] == "prior"
    assert s["problem"]["knobs"]["temperature_C"] == [60.0, 100.0]          # clipped to the robot
    assert s["problem"]["fixed"]["conc_precursor_mM"] == 0.25                # default
    studies = s["phases"]["prior"]["studies"]
    assert {x["source"] for x in studies} >= {"benchmark", "web"}
    bench_ids = [x["case_id"] for x in studies if x["source"] == "benchmark"]
    # sealed outcomes never reach the LLM; only the anchor is visible in the UI record
    for x in studies:
        if x["source"] == "benchmark":
            assert sum(p["outcomes"] is not None for p in x["points"]) == 1
    assert "28.5" not in prompts[-1]

    agent.confirm(sid, {})
    s = settle(agent, sid)
    assert s["phase"] == "stack"
    sel = [m["id"] for m in s["phases"]["stack"]["methods"] if m["selected"]]
    assert "continuum" in sel and "md_eam" in sel                             # temperature is a knob
    assert all(catalog.BY_ID[i]["status"] not in ("queued", "planned") for i in sel)
    # the three scales of the same stack: canonical order, unknown ids/icons dropped, lengths capped
    sc = s["phases"]["stack"]["scales"]
    assert [x["id"] for x in sc] == ["reactor", "atomistic"]                  # "galactic" dropped
    assert sc[0]["title"] == "R" + "x" * 139
    assert sc[0]["processes"] == [{"name": "Heat", "what": "brings the liquid to reflux",
                                   "formula": "dT/dt = 1", "icon": "chart"}]  # unknown icon -> chart
    assert sc[0]["links"] == ["nucleation"] and sc[0]["methods"] == ["continuum"]
    assert sc[1]["processes"][0]["icon"] == "collide"
    mx = s["phases"]["stack"]["mixing"]                                       # the mixing gate
    assert mx["verdict"] == "marginal" and mx["alternatives"][0]["verdict"] == "cfd"

    agent.confirm(sid, {})
    s = settle(agent, sid)
    assert s["phase"] == "sample" and s["phases"]["sample"]["candidates"]

    agent.confirm(sid, {})
    s = settle(agent, sid)
    B = s["phases"]["bench"]
    assert s["phase"] == "bench" and B["summary"]["n_scored"] >= 1, B
    assert B["variant"] in B["variants"]
    assert any(c["case_id"] in bench_ids and c["blind"] for c in B["cases"])

    agent.confirm(sid, {})
    s = settle(agent, sid)
    C = s["phases"]["case"]
    assert s["phase"] == "recipe"
    assert C["tornado"] and C["heatmap"] and C["sweeps"] and C["proposals"]
    assert s["phases"]["recipe"]["choice"] == C["proposals"][0]["id"]

    agent.confirm(sid, {})
    s = settle(agent, sid)
    assert s["phase"] == "robot"
    rr = agent.cfg.data_dir / "robot_requests"
    req = [f for f in rr.glob("*.json") if not f.name.endswith(".package.json")]
    assert len(req) == 1 and "self-building lab" in json.loads(req[0].read_text())["handoff"]
    # the protocol package for the self-building lab sits next to the request
    pk = json.loads((rr / req[0].name.replace(".json", ".package.json")).read_text())
    assert pk == s["phases"]["robot"]["package"]
    # the recipe listed no materials/equipment, so the agent filled them in and the package was rebuilt
    assert pk["materials"][0]["name"] == "HAuCl4" and pk["equipment"] == ["heated stirred vial block"]
    assert pk["materials_source"] == "recipe" and s["phases"]["recipe"]["recipe"]["materials"]
    assert _download(agent, sid) == pk
    assert pk["conditions"] and pk["measurements"] and pk["steps"] is not None
    assert {c["name"] for c in pk["conditions"]} == set(s["phases"]["robot"]["request"]["proposal"]["conditions"])

    agent.result(sid, {"measured": {"size_mean_nm": 15.2}, "notes": "first plate"})
    agent.result(sid, {"measured": {"size_mean_nm": 14.8}})
    s = agent.load(sid)
    rb = s["phases"]["robot"]
    assert s["status"] == "complete" and rb["results"][0]["quantity"] == "size_mean_nm"
    assert [r["n"] for r in rb["runs"]] == [1, 2] and rb["runs"][0]["notes"] == "first plate"
    assert rb["results"][0]["measured"] == 14.8
    fb = (agent.cfg.data_dir / "feedback.jsonl").read_text().splitlines()
    assert json.loads(fb[-1])["source"] == "robot"
