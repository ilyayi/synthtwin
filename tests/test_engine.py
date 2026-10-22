"""The engine orchestrator itself: study lifecycle across a restart, and ids
that never collide."""
from __future__ import annotations

from synthtwin.core import engine, runner


def test_restart_clears_busy(agent: engine.Agent) -> None:
    st = engine.new_study("y-1", "hi")
    st["busy"] = "benchmarking the stack"
    runner.save(agent.path("y-1"), st)
    a2 = engine.Agent(agent.cfg)
    s = a2.load("y-1")
    assert s["busy"] is None and "restart" in s["error"]


def test_same_second_studies_get_distinct_ids(agent: engine.Agent, settle) -> None:
    # the screener queues several families at once; ids must never collide
    text = "Find a synthesis route for perovskite films for solar cells, family A"
    ids = [agent.create(text)["id"] for _ in range(3)]
    assert len(set(ids)) == 3
    for sid in ids:
        settle(agent, sid)
