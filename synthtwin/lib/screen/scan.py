"""Rank material families by how worth a "beat the best reported X" study is.

`scan` takes the index rows and a query (material type + application, optional
metric / include / exclude / budget / explore share) and returns a leaderboard:
families (normalised material names) with their best reported figure of merit,
four 0-1 score components (record, data, sim, recent) and a study text ready to
queue as an agent study. `refine` is the optional deep pass: one LLM call that
checks the top families' values against their abstracts.
"""
from __future__ import annotations

import math
import re
import statistics
from typing import Any

from synthtwin.lib.screen import metrics as mm

WEIGHTS = {"record": 0.4, "data": 0.25, "sim": 0.25, "recent": 0.1}
# how well our simulation catalogue covers a synthesis route
SOLUTION = ("precipitation", "solution", "colloidal", "hot-injection", "hot injection", "sol-gel",
            "hydrothermal", "solvothermal", "coating", "self-assembly", "self assembly", "spin-coat",
            "spin coat", "slot-die", "slot die", "blade", "chemical bath", "impregnation", "electrospinning",
            "sonochemical", "microwave", "template-directed", "liquid-phase epitaxy", "spray pyrolysis")
SOLID = ("solid-state", "solid state", "ball milling", "mechanical mixing", "sintering", "spark plasma",
         "mechanochemical", "flux growth", "float zone", "bridgman", "arc melting", "induction melting",
         "combustion", "annealing", "calcination", "melting")

# family = normalised material name: no sizes, phase/descriptor words, sample codes
_STRIP_SIZE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:nm|μm|µm|um|mm|cm)\b", re.I)
_STRIP_WORDS = re.compile(r"\b(?:nanoparticles?|nanocrystals?|nanostructures?|nanosheets?|nanotubes?|"
                          r"nanowires?|nanorods?|nanofibers?|nanofibres?|thin films?|films?|powders?|"
                          r"single crystals?|crystals?|particles?|samples?|nano)\b", re.I)
_TRIM_CODE = re.compile(r"(?:[\s_-]+\d+)+$")


def norm(name: str) -> str:
    """The family behind a raw material name: 'CsPbI3 thin films' -> 'cspbi3'."""
    low = " ".join((name or "").lower().split())
    s = " ".join(_STRIP_WORDS.sub(" ", _STRIP_SIZE.sub(" ", low)).split())
    s = " ".join(_TRIM_CODE.sub("", s).split())
    return s or low


def sim_coverage(method: str) -> float:
    m = (method or "").lower()
    if any(k in m for k in SOLUTION):
        return 1.0
    if any(k in m for k in SOLID):
        return 0.6
    return 0.3


def _terms(q: str | list[str]) -> list[str]:
    if isinstance(q, list):
        parts = [str(x) for x in q]
    else:
        parts = re.split(r"\s*,\s*|\s+or\s+", str(q or ""), flags=re.I)
    return [p.strip() for p in parts if p.strip()]


def _matcher(term: str) -> re.Pattern:
    t = re.escape(term)
    if term.endswith("y"):   # battery -> batteries
        t += f"(?:{re.escape(term[:-1])}ies|es|s)?"
    else:
        t += r"(?:es|s)?"
    return re.compile(r"\b" + t + r"\b", re.I)


def _text(row: dict) -> str:
    return " ".join([row.get("title") or "", row.get("abstract") or ""])


def _paper(row: dict) -> dict:
    return {"title": row.get("title") or "", "doi": row.get("doi") or "", "url": row.get("url") or "",
            "year": row.get("year")}


def _fmt(v: float) -> str:
    return f"{v:.4g}"


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def label(families: list[dict], budget: int, explore: float) -> None:
    """Exploit the top round(budget*(1-explore)); explore thin-data gems below them."""
    for f in families:
        f["label"], f["suggest"] = None, False
    n_ex = min(_round_half_up(budget * (1 - explore)), len(families))
    for f in families[:n_ex]:
        f["label"], f["suggest"] = "exploit", True
    for f in families[n_ex:]:
        if sum(1 for x in families if x["label"]) >= budget:
            break
        if f["n_reports"] <= 2 or (f["components"]["record"] >= 0.8 and f["components"]["data"] < 0.5):
            f["label"], f["suggest"] = "explore", True


def _score(f: dict, weights: dict) -> float:
    return sum(w * f["components"][k] for k, w in weights.items() if k in f["components"])


def _sort(families: list[dict], weights: dict, budget: int, explore: float) -> list[dict]:
    for f in families:
        f["score"] = _score(f, weights)
    families.sort(key=lambda f: (-f["score"], -f["n_reports"], f["family"]))
    label(families, budget, explore)
    return families


def rank(result: dict, weights: dict | None = None, budget: int | None = None,
         explore: float | None = None) -> dict:
    """Re-rank a scan result under new weights (what the UI's sliders do)."""
    q = result["query"]
    out = dict(result)
    out["weights"] = weights or result["weights"]
    out["query"] = {**q, "budget": budget or q["budget"], "explore": explore if explore is not None else q["explore"]}
    out["families"] = _sort([dict(f) for f in result["families"]], out["weights"],
                            out["query"]["budget"], out["query"]["explore"])
    return out


def scan(rows: list[dict], query: dict) -> dict:
    material = str(query.get("material") or "").strip()
    application = str(query.get("application") or "").strip()
    if not material or not application:
        raise ValueError("name both a material type and an application")
    key = query.get("metric") or mm.pick(application)
    if not key:
        raise ValueError(f"no metric matches the application {application!r}; "
                         f"pass one of: {', '.join(mm.METRICS)}")
    if key not in mm.METRICS:
        raise ValueError(f"unknown metric {key!r}; pick one of: {', '.join(mm.METRICS)}")
    met = mm.METRICS[key]
    better = met["better"]
    inc = [_matcher(t) for t in _terms(query.get("include"))]
    exc = [_matcher(t) for t in _terms(query.get("exclude"))]
    budget = max(1, int(query.get("budget") or 3))
    explore = min(1.0, max(0.0, float(query.get("explore") if query.get("explore") is not None else 0.4)))
    weights = {**WEIGHTS, **{k: float(v) for k, v in (query.get("weights") or {}).items()}}
    take = max if better == "max" else min

    funnel = [("all", len(rows))]
    # 1. material match: any comma/"or"-separated term, in material/category/title/abstract
    mats = [_matcher(t) for t in _terms(material)]
    step = []
    for r in rows:
        hay = " ".join([r.get("material") or "", r.get("category") or "", r.get("title") or "",
                        r.get("abstract") or ""])
        if any(p.search(hay) for p in mats):
            step.append(r)
    funnel.append(("material", len(step)))
    # 2. application match: the application's words or the metric's own keywords, in title/abstract
    apps = [_matcher(t) for t in _terms(application)] + [_matcher(k) for k in met["apps"]]
    step = [r for r in step if any(p.search(_text(r)) for p in apps)]
    funnel.append(("application", len(step)))
    # 3. include/exclude words anywhere in the row's text or material name
    if inc:
        step = [r for r in step if any(p.search((r.get("material") or "") + " " + _text(r)) for p in inc)]
    if exc:
        step = [r for r in step if not any(p.search((r.get("material") or "") + " " + _text(r)) for p in exc)]
    funnel.append(("include/exclude", len(step)))
    # 4. rows that actually report the metric
    y0 = max((r.get("year") or 0) for r in rows) if rows else 0
    recent_years = {y0, y0 - 1, y0 - 2}
    reports: dict[str, list[dict]] = {}
    matched: dict[str, list[dict]] = {}
    for r in step:
        fam = norm(r.get("material") or "")
        if not fam:
            continue
        matched.setdefault(fam, []).append(r)
        vals = mm.extract(_text(r), key)
        if not vals:
            continue
        best = take(vals, key=lambda v: v["value"])
        reports.setdefault(fam, []).append({"value": best["value"], "snippet": best["snippet"],
                                            "id": r.get("id") or "", "paper": _paper(r)})
    funnel.append(("reports", sum(len(v) for v in reports.values())))

    fams = []
    for fam, reps in reports.items():
        rows_f = matched.get(fam) or []
        if not reps:
            continue
        best = take(reps, key=lambda d: d["value"])
        names: dict[str, int] = {}
        methods: dict[str, int] = {}
        for r in rows_f:
            names[r.get("material") or ""] = names.get(r.get("material") or "", 0) + 1
            methods[r.get("method") or "other"] = methods.get(r.get("method") or "other", 0) + 1
        method_top = sorted(methods, key=lambda m: -methods[m])
        main = method_top[0] if method_top else "other"
        richness = statistics.fmean([r.get("n_cond") or 0 for r in rows_f]) if rows_f else 0.0
        dois = {(d["paper"].get("doi") or f"t:{d['paper'].get('title')}") for d in reps}
        years = [d["paper"]["year"] for d in reps if d["paper"].get("year")]
        n_recent = sum(1 for d in reps if d["paper"].get("year") in recent_years)
        fams.append({"family": fam,
                     "names": sorted(names, key=lambda n: -names[n])[:3],
                     "best": {"value": best["value"], "unit": met["unit"], "snippet": best["snippet"],
                              "paper": best["paper"]},
                     "median": statistics.median(sorted(d["value"] for d in reps)),
                     "n_reports": len(reps), "n_papers": len(dois),
                     "methods": method_top[:3], "richness": round(richness, 3),
                     "years": [min(years), max(years)] if years else [],
                     "reports": sorted(reps, key=lambda d: -d["value"] if better == "max" else d["value"])[:30],
                     "_n_recent": n_recent, "_main": main})
    funnel.append(("families", len(fams)))

    # 5. components, labels, study text
    glob = take(fams, key=lambda f: f["best"]["value"]) if fams else None
    global_best = ({"value": glob["best"]["value"], "unit": met["unit"], "family": glob["family"],
                    "paper": glob["best"]["paper"]} if glob else None)
    out = []
    for f in fams:
        v, g = f["best"]["value"], (glob or f)["best"]["value"]
        rec = min(1.0, v / g) if better == "max" and g else min(1.0, g / v) if g else 0.0
        data = min(1.0, f["n_reports"] / 6) * min(1.0, f["richness"] / 3)
        sim = sim_coverage(f["_main"])
        recent = f["_n_recent"] / f["n_reports"] if f["n_reports"] else 0.0
        f["components"] = {"record": round(rec, 4), "data": round(data, 4), "sim": sim,
                           "recent": round(recent, 4)}
        f["reasons"] = {
            "record": f"best {_fmt(v)} {met['unit']} of a global {_fmt(g)} {met['unit']}",
            "data": f"{f['n_reports']} reports, {f['richness']:.1f} stated conditions per recipe on average",
            "sim": f"main route {f['_main']}: catalogue coverage {sim:.1f}",
            "recent": (f"{recent:.0%} of reports from {y0 - 2}-{y0}" if y0 else "no dated reports"),
        }
        f.pop("_n_recent")
        f.pop("_main")
        out.append(f)
    _sort(out, weights, budget, explore)
    for f in out:
        f["study_text"] = _study_text(f, met, application)
    q = {"material": material, "application": application, "metric": key,
         "include": str(query.get("include") or ""), "exclude": str(query.get("exclude") or ""),
         "budget": budget, "explore": explore}
    return {"query": q, "metric": {"key": key, "name": met["name"], "unit": met["unit"],
                                   "better": better},
            "funnel": [{"label": lab, "n": n} for lab, n in funnel],
            "global_best": global_best, "weights": weights, "families": out[:40]}


def _study_text(f: dict, met: dict, application: str) -> str:
    b, p = f["best"], f["best"]["paper"]
    name = f["names"][0] if f["names"] else f["family"]
    src = p.get("doi") or p.get("url") or ""
    when = f", {p['year']}" if p.get("year") else ""
    tail = f" ({p['title']}{when}{', ' + src if src else ''})" if p.get("title") else ""
    return (f"Beat the best reported {met['name']} for {name} {application}: "
            f"{_fmt(b['value'])} {met['unit']}{tail}. Make {name} by {f['methods'][0] if f['methods'] else 'the library route'} "
            f"(the family's main route in the library); the goal is a recipe that exceeds "
            f"{_fmt(b['value'])} {met['unit']}. Related syntheses in the library: "
            f"{f['n_reports']} reports from {f['n_papers']} papers.")


# ------------------------------------------------------------------ deep pass
_SYSTEM = """You check extracted figures of merit against the papers that reported them.
For each material family you get the reported best value, the sentence it came from \
and the paper's abstract. Judge whether the number really is what the family reports \
for this application (not a different quantity, a theoretical limit or an unrelated \
material), correct it if the abstract states a better one, and say in one short \
sentence why the record looks beatable or not. Do not invent numbers: if the abstract \
gives none, keep value_ok true and value null."""


def _schema() -> dict:
    return {"type": "object",
            "properties": {"reviews": {"type": "array", "items": {
                "type": "object",
                "properties": {"family": {"type": "string"}, "value_ok": {"type": "boolean"},
                               "value": {"type": ["number", "null"], "default": None},
                               "why_beatable": {"type": "string"}},
                "required": ["family", "value_ok", "value", "why_beatable"]}}},
            "required": ["reviews"]}


def refine(llm: Any, result: dict, rows: list[dict], k: int = 20) -> dict:
    """One LLM call over the top-k families' evidence; drop or correct rejected values."""
    fams = result["families"][:k]
    if not fams:
        return result
    by_id = {r.get("id"): r for r in rows}
    lines = []
    for f in fams:
        best = f["best"]
        ab = by_id.get(f["reports"][0]["id"], {}).get("abstract") if f["reports"] else None
        lines.append(f"Family: {f['family']} (also seen as: {', '.join(f['names'])})\n"
                     f"Reported best: {_fmt(best['value'])} {result['metric']['unit']}\n"
                     f"Evidence: \"{best['snippet']}\"\nAbstract: {ab or 'not available'}\n")
    ans = llm.role("work").ask(_SYSTEM, "\n\n".join(lines), _schema())   # light work (the refine default)
    reviews = ans.get("reviews") or []
    by_name = {f["family"]: f for f in result["families"]}
    met, better = result["metric"], result["metric"]["better"]
    take = max if better == "max" else min
    for rv in reviews:
        f = by_name.get(rv.get("family"))
        if not f:
            continue
        f["why_beatable"] = str(rv.get("why_beatable") or "")[:400]
        if rv.get("value_ok", True):
            continue   # the extraction stands
        if isinstance(rv.get("value"), (int, float)):   # corrected value
            f["reports"] = [d for d in f["reports"] if d["value"] != f["best"]["value"]]
            f["reports"].append({**f["best"], "id": "", "value": float(rv["value"]), "corrected": True})
        else:   # dropped: fall back to the family's next-best report
            f["reports"] = [d for d in f["reports"] if d["value"] != f["best"]["value"]]
    live = []
    for f in result["families"]:
        if not f["reports"]:
            continue
        best = take(f["reports"], key=lambda d: d["value"])
        vals = [d["value"] for d in f["reports"]]
        dois = {(d["paper"].get("doi") or f"t:{d['paper'].get('title')}") for d in f["reports"]}
        f["best"] = {"value": best["value"], "unit": met["unit"], "snippet": best["snippet"],
                     "paper": best["paper"]}
        f["median"] = statistics.median(sorted(vals))
        f["n_reports"] = len(vals)
        f["n_papers"] = len(dois)
        live.append(f)
    glob = take(live, key=lambda f: f["best"]["value"]) if live else None
    result["global_best"] = ({"value": glob["best"]["value"], "unit": met["unit"], "family": glob["family"],
                              "paper": glob["best"]["paper"]} if glob else None)
    for f in live:
        v, g = f["best"]["value"], (glob or f)["best"]["value"]
        rec = min(1.0, v / g) if better == "max" and g else min(1.0, g / v) if g else 0.0
        f["components"] = {**f["components"], "record": round(rec, 4)}
        f["reasons"] = {**f["reasons"],
                        "record": f"best {_fmt(v)} {met['unit']} of a global {_fmt(g)} {met['unit']}"
                                  + (" (checked)" if f.get("why_beatable") is not None else "")}
    q = result["query"]
    _sort(live, result["weights"], q["budget"], q["explore"])
    for f in live:
        f["study_text"] = _study_text(f, mm.METRICS[met["key"]], q["application"])
    result["families"] = live[:40]
    result["refined"] = True
    return result
