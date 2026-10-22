"""The stack step's LLM schemas: the methods at their scales, the chain of
physics the stack implements and the three-scale view — one schema for the
catalog's builtin systems, one for anything else — plus the cleaning both
answers go through."""
from __future__ import annotations

import re

from synthtwin import steps

SCALES = ["electronic", "atomistic", "mesoscale", "continuum", "reactor", "readout", "data"]
GENERIC_METHOD = {"type": "object", "properties": {
    "id": {"type": "string"}, "name": {"type": "string"}, "link": {"type": "string"},
    "scale": {"type": "string", "enum": SCALES}, "tool": {"type": "string"}, "role": {"type": "string"},
    "feeds": {"type": "string"}, "check": {"type": "string"}, "est_min": {"type": "number"},
    "selected": {"type": "boolean"}, "insight": {"type": "string"}},
    "required": ["id", "name", "link", "scale", "tool", "role", "feeds", "check", "est_min", "selected", "insight"]}
_STRS = {"type": "array", "items": {"type": "string"}}
CHAIN_LINK = {"type": "object", "properties": {
    "id": {"type": "string"}, "name": {"type": "string"}, "physics": {"type": "string"},
    "inputs": _STRS, "outputs": _STRS,
    "sensitivity": {"type": "string", "enum": ["high", "medium", "low"]}, "why": {"type": "string"},
    "data": {"type": "string"}, "competing": _STRS, "lessons": _STRS, "methods": _STRS},
    "required": ["id", "name", "physics", "inputs", "outputs", "sensitivity", "why", "data", "competing",
                 "lessons", "methods"]}
SCALE_IDS = ("reactor", "molecular", "atomistic")
SCALE_ICONS = ("heat", "stir", "dose", "evaporate", "flow", "light", "vessel", "plate", "molecule", "reaction",
               "nucleus", "growth", "collide", "charge", "ligand", "crystal", "atom", "bond", "electron",
               "spectrum", "chart")
SCALE_PROCESS = {"type": "object", "properties": {
    "name": {"type": "string"}, "what": {"type": "string"}, "formula": {"type": "string"},
    "icon": {"type": "string", "enum": list(SCALE_ICONS)}}, "required": ["name", "what"]}
SCALE_ITEM = {"type": "object", "properties": {
    "id": {"type": "string", "enum": list(SCALE_IDS)},
    "title": {"type": "string"}, "summary": {"type": "string"},
    "size": {"type": "string"}, "time": {"type": "string"},
    "processes": {"type": "array", "items": SCALE_PROCESS},
    "passes_down": {"type": "string"}, "links": _STRS, "methods": _STRS},
    "required": ["id", "title", "summary", "processes"]}

MIXING = {"type": "object", "properties": {
    "process": {"type": "string"}, "t_chem_s": {"type": "number"}, "t_chem_source": {"type": "string"},
    "vessel": {"type": "string"}, "rpm": {"type": "number"}, "impeller_mm": {"type": "number"},
    "vessel_mm": {"type": "number"}, "power_number": {"type": "number"},
    "t_mix_s": {"type": "number"}, "t_mix_source": {"type": "string"}, "note": {"type": "string"},
    "alternatives": {"type": "array", "items": {"type": "object", "properties": {
        "process": {"type": "string"}, "t_chem_s": {"type": "number"}}, "required": ["process", "t_chem_s"]}}},
    "required": ["process", "t_chem_s", "t_chem_source", "vessel"]}

SCHEMAS = {
    "stack": steps.llm_schema({"methods": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "selected": {"type": "boolean"}, "insight": {"type": "string"}},
        "required": ["id", "selected", "insight"]}}, "chain": {"type": "array", "items": CHAIN_LINK},
        "scales": {"type": "array", "items": SCALE_ITEM}, "mixing": MIXING},
        ["methods", "chain"]),
    "stack_other": steps.llm_schema({"chain": {"type": "array", "items": CHAIN_LINK},
                                     "methods": {"type": "array", "items": GENERIC_METHOD},
                                     "scales": {"type": "array", "items": SCALE_ITEM},
                                     "mixing": MIXING},
                                    ["chain", "methods"]),
}


def clean_chain(chain: list[dict]) -> list[dict]:
    """The stack's chain links with snake_case ids and the method ids each link uses."""
    out, seen = [], set()
    for c in chain:
        cid = re.sub(r"[^a-z0-9_]+", "_", str(c.get("id") or c.get("name") or "").lower()).strip("_")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append({**c, "id": cid, "methods": [re.sub(r"[^a-z0-9_]+", "_", str(m).lower()).strip("_")
                                                for m in c.get("methods") or []]})
    return out


def clean_scales(scales: list[dict], chain: list[dict], methods: list[dict]) -> list[dict]:
    """The stack's three scales: canonical order, unknown icons/links/methods dropped, lengths capped."""
    link_ids = {c.get("id") for c in chain or []}
    method_ids = {m.get("id") for m in methods or []}
    out: dict[str, dict] = {}
    for x in scales or []:
        sid = str(x.get("id", "")).lower()
        if sid not in SCALE_IDS or sid in out:
            continue
        procs = []
        for p in (x.get("processes") or [])[:6]:
            name = str(p.get("name", "")).strip()[:60]
            if not name:
                continue
            procs.append({"name": name, "what": str(p.get("what", "")).strip()[:140],
                          "formula": str(p.get("formula", "")).strip()[:120],
                          "icon": p.get("icon") if p.get("icon") in SCALE_ICONS else "chart"})
        if not procs:                      # a scale without a single usable process is not kept
            continue
        out[sid] = {"id": sid, "title": str(x.get("title", "")).strip()[:140],
                    "summary": str(x.get("summary", "")).strip()[:400],
                    "size": str(x.get("size", "")).strip()[:40], "time": str(x.get("time", "")).strip()[:40],
                    "processes": procs, "passes_down": str(x.get("passes_down", "")).strip()[:160],
                    "links": [l for l in (x.get("links") or []) if l in link_ids][:12],
                    "methods": [m for m in (x.get("methods") or []) if m in method_ids][:12]}
    return [out[k] for k in SCALE_IDS if k in out]
