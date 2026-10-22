"""The stack step: a chain/scales answer with nothing usable stores nothing,
not something half-empty."""
from __future__ import annotations

from synthtwin.core import engine


def test_stack_scales_absent_and_partial(agent: engine.Agent) -> None:
    # a stack answer with no scales at all: nothing stored, nothing breaks
    s = engine.new_study("sc-1", "gold 15 nm")
    agent.apply(s, "stack", {"reply": "ok", "ready": True}, {})
    assert "scales" not in s["phases"]["stack"]
    # scales that do not survive cleaning (no usable process) are dropped, not stored half-empty
    s = engine.new_study("sc-2", "gold 15 nm")
    agent.apply(s, "stack", {"reply": "ok", "ready": True,
                             "scales": [{"id": "molecular", "title": "t", "summary": "s",
                                         "processes": [{"what": "no name"}]}]}, {})
    assert "scales" not in s["phases"]["stack"]


def test_mixing_gate(agent: engine.Agent) -> None:
    from synthtwin.steps.stack import mixing
    # Grenville for a 25 mm bar in a 58 mm flask at 600 rpm: 5.2 / (0.6^(1/3) * 10) * (58/25)^2
    assert abs(mixing.grenville(600, 25, 58) - 3.32) < 0.01
    slow = mixing.gate({"process": "citrate", "t_chem_s": 30, "rpm": 600, "impeller_mm": 25, "vessel_mm": 58,
                        "alternatives": [{"process": "NaBH4", "t_chem_s": 0.01}, {"process": "", "t_chem_s": 1}]})
    assert slow["t_mix_from"] == "grenville" and slow["verdict"] == "marginal"     # Da = 0.11
    assert [a["verdict"] for a in slow["alternatives"]] == ["cfd"]                   # Da = 332; nameless dropped
    # a simulated/measured t_mix wins over the correlation; both Da are kept
    sim = mixing.gate({"t_chem_s": 30, "t_mix_s": 0.67, "rpm": 600, "impeller_mm": 25, "vessel_mm": 58})
    assert sim["verdict"] == "lumped" and sim["t_mix_from"] == "given" and sim["Da_grenville"] > sim["Da"]
    # a well plate: no stirrer, only a mixing time
    assert mixing.gate({"t_chem_s": 600, "t_mix_s": 2})["verdict"] == "lumped"
    # nothing usable -> no gate, nothing stored
    assert mixing.gate({"t_chem_s": 5}) is None and mixing.gate("x") is None
    s = engine.new_study("mx-1", "gold 15 nm")
    agent.apply(s, "stack", {"reply": "ok", "ready": True, "mixing": {"t_chem_s": 0}}, {})
    assert "mixing" not in s["phases"]["stack"]
    agent.apply(s, "stack", {"reply": "ok", "ready": True,
                             "mixing": {"process": "NaBH4", "t_chem_s": 0.01, "t_mix_s": 0.67}}, {})
    assert s["phases"]["stack"]["mixing"]["verdict"] == "cfd"
