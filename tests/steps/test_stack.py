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
