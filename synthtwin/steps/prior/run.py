"""The prior step's handlers: apply (the agent asked for a sharper literature
search), work (gather related studies: benchmark cards, the mined library,
the literature) and confirm (the gate into stack)."""
from __future__ import annotations

from typing import Callable

from synthtwin.core import catalog, systems
from synthtwin.steps.prior import prior, triage


def apply(agent, s: dict, ans: dict) -> Callable | None:
    """A search query in the answer: run it, then let the agent summarise what it added."""
    if not (ans.get("search") or "").strip():
        return None
    q = ans["search"].strip()
    sid = s["id"]
    return lambda: (agent._busy(sid, f"searching the literature for: {q}"), web(agent, sid, q),
                    agent.turn(sid, "The new literature search finished; summarise what it added."))


def work(agent, sid: str) -> None:
    """The phase's background job: related studies from every source, then the agent's turn."""
    s = agent.load(sid)
    pb = s["problem"]
    studies = prior.from_cards(pb, list(agent.cards().values())) + prior.from_library(pb, agent.library())
    studies.sort(key=lambda x: -x["relevance"])
    agent.mutate(sid, lambda s: s["phases"]["prior"].update(studies=studies, status="working"))
    if agent.cfg.web and getattr(agent.cfg, "triage", None):
        agent._busy(sid, "triaging the paper index (about 1 min)")
        try:
            t = triage.run(agent.cfg.llm, pb, agent.cfg.triage)
            agent.mutate(sid, lambda s: s["phases"]["prior"].update(triage=t))
        except Exception as exc:
            agent.mutate(sid, lambda s: s["phases"]["prior"].update(triage_error=str(exc)))
    if agent.cfg.web:
        agent._busy(sid, "searching the literature (1-3 min)")
        try:
            web(agent, sid, "")
        except Exception as exc:
            agent.mutate(sid, lambda s: s["phases"]["prior"].update(web_error=str(exc)))
    agent.mutate(sid, lambda s: s["phases"]["prior"].update(status="awaiting_user"))
    agent.turn(sid)


def web(agent, sid: str, focus: str) -> None:
    """Search the literature (optionally focused on one thing) and merge what it finds."""
    s = agent.load(sid)
    pb = dict(s["problem"])
    if focus:
        pb["search_focus"] = focus
    have = [x["title"] for x in s["phases"]["prior"].get("studies", [])][:20]
    found, reply = prior.web_search(agent.cfg.llm, pb, have,
                                    triage.seeds(s["phases"]["prior"].get("triage")))

    def put(s):
        P = s["phases"]["prior"]
        old = P.get("studies", [])
        n0 = sum(x["source"] == "web" for x in old)
        for i, x in enumerate(found):
            x["id"] = f"web-{n0 + i}"
        P["studies"] = sorted(old + found, key=lambda x: -x["relevance"])
        P["web_reply"] = reply
    agent.mutate(sid, put)


def confirm(agent, sid: str, s: dict, body: dict) -> None:
    """The gate: the chosen studies are frozen; the stack is the catalog's default
    (builtins) or designed by the agent in its next turn (any other system)."""
    pb = s["problem"]
    if systems.is_builtin(pb):
        methods = catalog.default_stack(pb["material"], list(pb["targets"]), list(pb["knobs"]))
        est = catalog.estimate([m["id"] for m in methods if m["selected"]])
    else:   # the agent designs it in its next turn
        methods, est = [], catalog.generic_estimate([])

    def go(s):
        agent._advance(s, "stack")
        s["phases"]["stack"].update(methods=methods, status="awaiting_user", estimate=est)
    agent.mutate(sid, go)
    agent.background(sid, "choosing the simulation stack", lambda: agent.turn(sid))
