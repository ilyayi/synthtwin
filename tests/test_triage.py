"""Paper-index triage: off by default, papers cleaned and DOI-checked, seeds reach the literature scout,
and the CLI backend allows exactly the connector tools it was given."""
from __future__ import annotations

import json
from pathlib import Path

from synthtwin.core import engine, llm
from synthtwin.steps.prior import prior, triage

EXAMPLES = Path(__file__).parent.parent / "examples"
PB = {"system": "colloid", "material": "Au", "method": "citrate"}


def _answer(system: str, prompt: str, schema: dict) -> dict:
    if schema is triage.SCHEMA:
        return {"reply": "Well covered.", "counts": [{"query": "Turkevich", "n": 812}], "papers": [
            {"title": "Size vs citrate ratio", "doi": "https://doi.org/10.1016/J.JCIS.2016.10.065.", "year": "2017",
             "kind": "sweep", "why": "sweeps the knob", "reports": "size vs citrate:Au"},
            {"title": "Size vs citrate ratio (dup)", "doi": "10.1016/j.jcis.2016.10.065", "kind": "sweep", "why": "x"},
            {"title": "A review", "doi": "", "kind": "review", "why": "background"}]}
    return {"reply": "", "studies": []}


def test_run_cleans_dedups_and_marks_dois(monkeypatch) -> None:
    monkeypatch.setattr(triage, "crossref_ok", lambda doi, title: doi.startswith("10.1016"))
    seen = {}
    stub = llm.Stub(_answer)
    orig = stub.ask
    stub.ask = lambda *a, **kw: (seen.update(kw), orig(*a, **kw))[1]
    t = triage.run(stub, PB)
    assert seen["mcp"] == triage.BACKENDS["valency"]
    assert [p["doi"] for p in t["papers"]] == ["10.1016/j.jcis.2016.10.065", ""]
    assert t["papers"][0]["verified"] is True and t["papers"][1]["verified"] is False
    assert t["papers"][0]["url"] == "https://doi.org/10.1016/j.jcis.2016.10.065"
    assert t["counts"] == [{"query": "Turkevich", "n": 812}]
    assert triage.seeds(t)[0].startswith("Size vs citrate ratio (2017)")


def test_seeds_reach_the_scout() -> None:
    got = {}
    stub = llm.Stub(lambda system, prompt, schema: (got.update(prompt=prompt), {"reply": "", "studies": []})[1])
    prior.web_search(stub, PB, None, ["Paper A (2017) — sweep"])
    assert "Papers triaged from a paper index" in got["prompt"] and "Paper A (2017)" in got["prompt"]
    prior.web_search(stub, PB)
    assert "triaged" not in got["prompt"]


def test_off_by_default() -> None:
    cfg = engine.AgentConfig(Path("/tmp/x"), EXAMPLES / "recipes.jsonl", EXAMPLES / "robot.yaml")
    assert cfg.triage is None


def test_cli_allows_only_the_given_connector_tools(monkeypatch, tmp_path: Path) -> None:
    calls = []

    class R:
        returncode, stderr = 0, ""
        stdout = json.dumps({"structured_output": {"reply": "", "papers": []}})

    monkeypatch.setattr(llm.subprocess, "run", lambda cmd, **kw: (calls.append(cmd), R())[1])
    c = llm.ClaudeCLI()
    c.ask("sys", "p", triage.SCHEMA)
    assert "--strict-mcp-config" in calls[-1] and "--allowedTools" not in calls[-1]
    c.ask("sys", "p", triage.SCHEMA, mcp=triage.BACKENDS["valency"])
    cmd = calls[-1]
    assert "--strict-mcp-config" not in cmd
    assert cmd[cmd.index("--allowedTools") + 1] == ",".join(triage.BACKENDS["valency"])
    assert "--tools" not in cmd and "Bash" in cmd[cmd.index("--disallowedTools") + 1]
