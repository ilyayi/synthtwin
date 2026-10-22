"""The goal step: the problem patch the agent writes, its cleaning and the
confirm gate into prior."""
from __future__ import annotations

import pytest

from synthtwin.core import engine, runner
from synthtwin.steps.goal.schema import check_problem


def test_goal_needs_targets_and_knobs(agent: engine.Agent) -> None:
    assert check_problem({"material": "Au", "targets": {}, "knobs": {"pH": [5, 3]}}) == [
        "no target quantity", "knob pH: low 5 is not below high 3"]
    sid = engine.new_study("x-1", "hi")["id"]
    st = engine.new_study(sid, "hi")
    from synthtwin.core import runner
    runner.save(agent.path(sid), st)
    with pytest.raises(ValueError, match="not complete"):
        agent.confirm(sid, {"phase": "goal"})
