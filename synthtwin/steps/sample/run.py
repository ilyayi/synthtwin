"""The sample step's handlers: apply (the agent's pick of benchmark studies)
and confirm (the gate into bench: the benchmark runs)."""
from __future__ import annotations

from typing import Callable

from synthtwin import steps


def apply(agent, s: dict, ans: dict) -> Callable | None:
    """The agent's pick of studies stays within the candidates it was shown."""
    if not isinstance(ans.get("selected"), list):
        return None
    P = s["phases"]["sample"]
    ids = {c["id"] for c in P.get("candidates", [])}
    sel = [i for i in ans["selected"] if i in ids]
    if sel:
        for c in P["candidates"]:
            c["selected"] = c["id"] in sel
    return None


def confirm(agent, sid: str, s: dict, body: dict) -> None:
    """The gate: the researcher's ticks win; the benchmark starts right after."""
    if isinstance(body.get("selected"), list):
        def tick(x):
            for c in x["phases"]["sample"].get("candidates", []):
                c["selected"] = c["id"] in body["selected"]
        agent.mutate(sid, tick)
        s = agent.load(sid)
    sel = [c for c in s["phases"]["sample"].get("candidates", []) if c.get("selected")]
    if not sel and not body.get("skip"):
        raise ValueError("select at least one study, or skip the benchmark")
    agent.mutate(sid, lambda s: agent._advance(s, "bench"))
    agent.background(sid, "benchmarking the stack", lambda: steps.run("bench").work(agent, sid))
