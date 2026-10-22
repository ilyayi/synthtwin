"""Literature triage through a paper index (optional, off by default).

Before the literature scout opens papers, an agent with read-only access to a paper index (the Valency
connector: semantic and keyword search over abstracts, forward citations, similar papers, counts) ranks
the papers worth opening for THIS goal and says which abstracts report numbers. The scout then starts
from those papers. The index returns metadata and abstracts only, so triage never supplies data points:
conditions and outcomes still come from the scout reading the paper. Every DOI is checked against
CrossRef (the title must match); unverified ones are kept but marked.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from typing import Any

from synthtwin import protocols, steps

BACKENDS = {"valency": tuple(f"mcp__claude_ai_Valency__{t}" for t in (
    "semantic_search_papers", "search_by_abstract", "search_by_abstract_batch", "get_paper_by_id",
    "get_citing_papers", "find_similar_papers", "count_papers"))}

SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "2-4 sentences: what the index holds for this goal, where it is thin"},
        "papers": {"type": "array", "items": {"type": "object", "properties": {
            "title": {"type": "string"}, "doi": {"type": "string"}, "year": {"type": "string"},
            "venue": {"type": "string"}, "citations": {"type": "integer"},
            "kind": {"type": "string", "enum": ["sweep", "method", "simulation", "review", "other"]},
            "reports": {"type": "string", "description": "what the abstract says it measured or varied, or ''"},
            "why": {"type": "string", "description": "one line: why open it for this goal"}},
            "required": ["title", "doi", "kind", "why"]}},
        "counts": {"type": "array", "items": {"type": "object", "properties": {
            "query": {"type": "string"}, "n": {"type": "integer"}}, "required": ["query", "n"]}},
    },
    "required": ["reply", "papers"],
}

SYSTEM = protocols.prompt("prior.triage")


def run(llm: Any, problem: dict, backend: str = "valency", limit: int = 12, verify: bool = True) -> dict:
    """Ranked papers to open for this goal: {reply, papers: [... + verified], counts, backend}."""
    tools = BACKENDS[backend]
    # name the tools: connector tools may be deferred (loaded on demand), and an unnamed one looks absent
    prompt = ("Researcher's problem:\n" + json.dumps(problem, indent=1) + f"\n\nReturn at most {limit} papers."
              + "\n\nThe paper-index tools (load them by name if they are deferred): " + ", ".join(tools))
    ans = llm.role(steps.role("prior", "triage")).ask(SYSTEM, prompt, SCHEMA, mcp=tools)
    papers, seen = [], set()
    for p in ans.get("papers") or []:
        doi = _doi(p.get("doi", ""))
        key = doi or p.get("title", "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        papers.append({"title": str(p.get("title", ""))[:300], "doi": doi, "year": str(p.get("year", ""))[:10],
                       "venue": str(p.get("venue", ""))[:120], "citations": p.get("citations"),
                       "kind": p.get("kind", "other"), "reports": str(p.get("reports", ""))[:300],
                       "why": str(p.get("why", ""))[:200],
                       "url": f"https://doi.org/{doi}" if doi else ""})
        if len(papers) >= limit:
            break
    if verify:
        for p in papers:
            p["verified"] = crossref_ok(p["doi"], p["title"]) if p["doi"] else False
    counts = [{"query": str(c.get("query", ""))[:120], "n": int(c.get("n", 0))} for c in ans.get("counts") or []][:4]
    return {"backend": backend, "reply": ans.get("reply", ""), "papers": papers, "counts": counts}


def seeds(t: dict | None, n: int = 8) -> list[str]:
    """The triaged papers as one-line hints for the literature scout (sweeps first, verified first)."""
    rank = {"sweep": 0, "simulation": 1, "method": 2, "review": 3, "other": 4}
    ps = sorted((t or {}).get("papers") or [], key=lambda p: (rank.get(p["kind"], 5), not p.get("verified")))
    return [f"{p['title']} ({p['year']}) {p['url'] or ''} — {p['reports'] or p['why']}".strip() for p in ps[:n]]


def _doi(s: str) -> str:
    m = re.search(r"10\.\d{4,9}/\S+", s or "")
    return m.group(0).rstrip(".,;)").lower() if m else ""


def crossref_ok(doi: str, title: str, timeout: float = 8.0) -> bool | None:
    """True when CrossRef knows the DOI and its title matches; False when it does not; None when unreachable."""
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "synthtwin"}),
                                    timeout=timeout) as r:
            got = (json.load(r).get("message", {}).get("title") or [""])[0]
    except urllib.error.HTTPError as exc:
        return False if exc.code == 404 else None
    except Exception:
        return None
    norm = lambda x: re.sub(r"[^a-z0-9]+", " ", re.sub(r"<[^>]+>", "", x.lower())).strip()
    return SequenceMatcher(None, norm(got), norm(title)).ratio() >= 0.8
