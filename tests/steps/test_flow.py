"""The whole pipeline end to end with a scripted LLM and the stub predictor:
goal -> related studies -> stack -> sample -> benchmark -> case -> recipe ->
robot (the fixtures live in tests/conftest.py)."""
from __future__ import annotations

import json

import pytest

from synthtwin.core import catalog, engine


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
    req = list((agent.cfg.data_dir / "robot_requests").glob("*.json"))
    assert len(req) == 1 and "self-building lab" in json.loads(req[0].read_text())["handoff"]

    agent.result(sid, {"measured": {"size_mean_nm": 15.2}})
    s = agent.load(sid)
    assert s["status"] == "complete" and s["phases"]["robot"]["results"][0]["quantity"] == "size_mean_nm"
    fb = (agent.cfg.data_dir / "feedback.jsonl").read_text().splitlines()
    assert json.loads(fb[-1])["source"] == "robot"
