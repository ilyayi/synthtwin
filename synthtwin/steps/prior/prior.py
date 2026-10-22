"""Related studies for a problem, from three sources:

    benchmark   curated one-factor sweeps (cards). Only the anchor's outcomes
                are visible; the rest stay sealed until the benchmark has
                scored the model on them (they are a blind test).
    library     published recipes grouped by paper; a paper with several
                recipes that differ in one or two conditions is a sweep.
    web         the agent searches the literature and extracts sweeps with
                citations. Agent-extracted, unverified, and not blind (the
                model may be calibrated on numbers it has seen).
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from synthtwin import protocols

CONDITION_KEYS = ("temperature_C", "time_min", "pH", "ratio_reductant_precursor", "conc_precursor_mM",
                  "conc_reductant_mM", "conc_capping_mM", "conc_base_mM", "ratio_seed_precursor", "seed_d_nm",
                  "n_injections", "injection_interval_min", "total_volume_ml", "stirring_rpm", "addition_rate_ml_min")


def _relevance(problem: dict, material: str, method: str, swept: list[str], quantities: list[str]) -> tuple[float, list[str]]:
    why, s = [], 0.0
    if material == problem.get("material"):
        s += 0.4
        why.append(f"same material ({material})")
    pm = (problem.get("method") or "").lower()
    if pm and method and (pm in method.lower() or method.lower() in pm):
        s += 0.2
        why.append("same method")
    knobs = set(problem.get("knobs") or {})
    hit = [k for k in swept if k in knobs]
    if hit:
        s += 0.25
        why.append(f"sweeps your knob {', '.join(hit)}")
    tq = set(problem.get("targets") or {})
    qh = [q for q in quantities if q in tq]
    if qh:
        s += 0.15
        why.append(f"measures {', '.join(qh)}")
    return round(s, 2), why


def from_cards(problem: dict, cards: list[dict], revealed: dict[str, dict] | None = None) -> list[dict]:
    """revealed: case_id -> {label: {quantity: value}} once the benchmark has scored that case."""
    out = []
    for c in cards:
        rel, why = _relevance(problem, c.get("material", ""), c.get("method", ""),
                              [c.get("sweep_variable", "")], c.get("quantities", []))
        if rel < 0.4:
            continue
        rev = (revealed or {}).get(c["case_id"])
        anchor = {o["quantity"]: o["value"] for o in c.get("anchor_outcomes", [])}
        pts = []
        for p in c.get("points", []):
            if rev is not None:
                outs, state = rev.get(p["label"]), "measured"
            elif p["label"] == c.get("anchor_label"):
                outs, state = anchor, "anchor (visible)"
            else:
                outs, state = None, "sealed until benchmarked"
            pts.append({"label": p["label"], "value": p.get("value"), "conditions": p.get("conditions", {}),
                        "outcomes": outs, "state": state})
        fixed = _fixed([p.get("conditions", {}) for p in c.get("points", [])], c.get("sweep_variable", ""))
        out.append({"id": f"case:{c['case_id']}", "case_id": c["case_id"], "source": "benchmark",
                    "title": c.get("paper_title", ""), "url": c.get("paper_url", ""), "year": c.get("published", ""),
                    "material": c.get("material", ""), "method": c.get("method", ""),
                    "swept": [{"key": c.get("sweep_variable", ""), "values": [p.get("value") for p in c.get("points", [])]}],
                    "fixed": fixed, "quantities": c.get("quantities", []), "points": pts,
                    "blind": rev is None, "relevance": rel, "why": why,
                    "note": "blind test: outcomes sealed until the benchmark has scored the model"
                            if rev is None else "benchmarked: outcomes revealed"})
    return out


def _fixed(conds: list[dict], swept: str | list[str]) -> dict:
    swept = {swept} if isinstance(swept, str) else set(swept)
    keys = set.intersection(*(set(c) for c in conds)) if conds else set()
    return {k: conds[0][k] for k in sorted(keys - swept) if len({c[k] for c in conds}) == 1}


def from_library(problem: dict, library: list[Any], limit: int = 12) -> list[dict]:
    by_paper: dict[str, list[dict]] = defaultdict(list)
    for r in library:
        r = r if isinstance(r, dict) else r.model_dump()
        if r.get("material") != problem.get("material"):
            continue
        key = r.get("paper_doi") or r.get("paper_title") or r.get("recipe_id")
        by_paper[key].append(r)
    out = []
    for key, rs in by_paper.items():
        conds = [r.get("conditions") or {} for r in rs]
        keys = sorted({k for c in conds for k in c})
        swept = [k for k in keys if len({c.get(k) for c in conds}) > 1] if len(rs) > 1 else []
        quantities = sorted({o["quantity"] for r in rs for o in r.get("outcomes") or []})
        rel, why = _relevance(problem, rs[0].get("material", ""), rs[0].get("method", ""), swept, quantities)
        if not quantities:
            rel = round(rel * 0.5, 2)
            why.append("no outcomes reported")
        pts = [{"label": r.get("recipe_id", ""), "value": None, "conditions": r.get("conditions") or {},
                "outcomes": {o["quantity"]: o["value"] for o in r.get("outcomes") or []} or None,
                "state": "reported" if r.get("outcomes") else "no outcome"} for r in rs[:12]]
        out.append({"id": f"lib:{key}", "source": "library", "title": rs[0].get("paper_title") or key,
                    "url": rs[0].get("paper_url") or (f"https://doi.org/{rs[0]['paper_doi']}" if rs[0].get("paper_doi") else ""),
                    "year": rs[0].get("published", ""), "material": rs[0].get("material", ""),
                    "method": rs[0].get("method", ""),
                    "swept": [{"key": k, "values": sorted({c[k] for c in conds if k in c})} for k in swept],
                    "fixed": _fixed(conds, swept) if len(rs) > 1 else dict(conds[0]),
                    "quantities": quantities, "points": pts, "blind": False, "relevance": rel, "why": why,
                    "note": f"{len(rs)} recipe(s) from the mined library"})
    out.sort(key=lambda s: (-s["relevance"], -len(s["points"])))
    return out[:limit]


WEB_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "2-5 sentences for the researcher: what the literature says for their goal"},
        "studies": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "title": {"type": "string"}, "url": {"type": "string"}, "year": {"type": "string"},
                "material": {"type": "string"}, "method": {"type": "string"},
                "swept_key": {"type": "string"}, "swept_unit": {"type": "string"},
                "fixed": {"type": "array", "items": {"type": "object", "properties": {
                    "key": {"type": "string"}, "value": {"type": "number"}}, "required": ["key", "value"]}},
                "points": {"type": "array", "items": {"type": "object", "properties": {
                    "swept_value": {"type": "number"},
                    "outcomes": {"type": "array", "items": {"type": "object", "properties": {
                        "quantity": {"type": "string"}, "value": {"type": "number"}, "unit": {"type": "string"}},
                        "required": ["quantity", "value"]}}},
                    "required": ["swept_value", "outcomes"]}},
                "takeaway": {"type": "string"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            },
            "required": ["title", "url", "swept_key", "points", "takeaway", "confidence"],
        }},
    },
    "required": ["reply", "studies"],
}

# the scout's system prompt lives in synthtwin/protocols/search-data.md (the search-data protocol)
WEB_SYSTEM = protocols.prompt("prior.web_system").replace("{condition_keys}", ", ".join(CONDITION_KEYS))


def web_search(llm: Any, problem: dict, exclude: list[str] | None = None,
               seeds: list[str] | None = None) -> tuple[list[dict], str]:
    prompt = ("Researcher's problem:\n" + json.dumps(problem, indent=1)
              + ("\n\nAlready known (skip these): " + "; ".join(exclude) if exclude else "")
              + ("\n\nPapers triaged from a paper index (open these first; they are leads, not data):\n- "
                 + "\n- ".join(seeds) if seeds else ""))
    ans = llm.ask(WEB_SYSTEM, prompt, WEB_SCHEMA, web=True)
    out = []
    for i, s in enumerate(ans.get("studies") or []):
        key = s.get("swept_key", "")
        pts = [{"label": f"{key}={p['swept_value']:g}", "value": p["swept_value"],
                "conditions": {key: p["swept_value"]},
                "outcomes": {o["quantity"]: o["value"] for o in p.get("outcomes") or []} or None,
                "state": "reported"} for p in s.get("points") or [] if isinstance(p.get("swept_value"), (int, float))]
        fixed = {f["key"]: f["value"] for f in s.get("fixed") or []}
        for p in pts:
            p["conditions"] = {**fixed, **p["conditions"]}
        quantities = sorted({q for p in pts for q in (p["outcomes"] or {})})
        rel, why = _relevance(problem, s.get("material", ""), s.get("method", ""), [key], quantities)
        out.append({"id": f"web:{i}:{s.get('url', '')[:80]}", "source": "web", "title": s.get("title", ""),
                    "url": s.get("url", ""), "year": s.get("year", ""), "material": s.get("material", ""),
                    "method": s.get("method", ""), "swept": [{"key": key, "values": [p["value"] for p in pts],
                                                               "unit": s.get("swept_unit", "")}],
                    "fixed": fixed, "quantities": quantities, "points": pts, "blind": False,
                    "relevance": rel, "why": why, "takeaway": s.get("takeaway", ""),
                    "confidence": s.get("confidence", "low"),
                    "note": "agent-extracted from the paper, unverified; not blind"})
    return out, ans.get("reply", "")


def load_cards(cards_dir: Path | None) -> list[dict]:
    if not cards_dir or not Path(cards_dir).is_dir():
        return []
    out = []
    for f in sorted(Path(cards_dir).glob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    return out
