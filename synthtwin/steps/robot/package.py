"""The protocol package a self-building lab receives (e.g. Self-Building Labs).

It only passes information: what to make, under which conditions, with which
materials, on which equipment and tools, what to measure and what counts as a
pass. The lab decides how to run it on its own hardware; the robot's capability
list never filters the package (see the handoff protocol).

    build(s, request, robot) -> package dict   (plain JSON, written next to the request)

Every field comes from the study: the problem (material, method, knobs, fixed
values, targets), the chosen proposal (conditions, predicted bands, reagents,
steps) and the recipe write-up (materials, equipment, steps, checks). When the
recipe lists no materials or equipment, they are read off the steps with a small
generic vocabulary and marked "from the steps" so the lab knows to confirm them;
the agent then lists both properly (robot.fill) and the package is rebuilt.
"""
from __future__ import annotations

import re
import time

FORMAT = "synthtwin.protocol-package/1"

# key suffix -> unit (problem keys are snake_case and end in their unit, e.g. coating_speed_m_min)
UNITS = [("_wt_pct", "wt %"), ("_vol_pct", "vol %"), ("_pct", "%"), ("_m_min", "m/min"), ("_mm_s", "mm/s"),
         ("_ml_min", "mL/min"), ("_ul_min", "µL/min"), ("_C", "°C"), ("_K", "K"), ("_um", "µm"), ("_nm", "nm"),
         ("_mm", "mm"), ("_mM", "mM"), ("_uM", "µM"), ("_M", "M"), ("_mg_ml", "mg/mL"), ("_ml", "mL"),
         ("_ul", "µL"), ("_g", "g"), ("_mg", "mg"), ("_min", "min"), ("_s", "s"), ("_h", "h"), ("_rpm", "rpm"),
         ("_Pa_s", "Pa·s"), ("_bar", "bar"), ("_kPa", "kPa")]

# words in the steps/method -> the equipment or tool they need (generic across syntheses and coatings)
EQUIPMENT = [
    (r"slot[- ]die", "slot-die coater (adjustable gap, metering pump)"),
    (r"spin[- ]coat", "spin coater"),
    (r"blade|doctor", "blade coater"),
    (r"hot[- ]?plate|soft[- ]bake", "hot plate"),
    (r"oven|furnace|imidi[sz]|anneal|cure", "oven or furnace with a programmable ramp"),
    (r"reflux|condenser", "reflux condenser"),
    (r"round[- ]bottom|flask", "round-bottom flask with heating mantle"),
    (r"\d+[- ]well|well plate|microplate", "well plate with heated, stirred block"),
    (r"stir", "magnetic stirrer"),
    (r"pipett|dispens|liquid handler", "pipettes or liquid handler"),
    (r"inject", "syringe for fast injection"),
    (r"syringe pump|pump flow|metering pump", "syringe or metering pump"),
    (r"centrifug", "centrifuge"),
    (r"sonicat|ultrason", "ultrasonic bath"),
    (r"degas|vacuum", "vacuum line or desiccator for degassing"),
    (r"nitrogen|\bN2\b|argon|glove ?box|inert", "inert gas (N2 or Ar)"),
    (r"uv[- ]ozone", "UV-ozone cleaner"),
    (r"feeler gauge", "feeler gauges"),
    (r"ice bath", "ice bath"),
    (r"\bpH\b", "pH meter"),
    (r"\d\s*(g|mg)\b|weigh", "analytical balance"),
    (r"filter|syringe filter", "syringe filters"),
]

# measured quantity -> instrument (by the quantity's name)
INSTRUMENTS = [
    (r"lspr|absorb|extinct|uv_?vis|band_?gap|abs_", "UV-Vis spectrometer"),
    (r"dls|hydrodynamic|pdi", "DLS"),
    (r"plqy|pl_|emission|fluoresc", "fluorimeter (PL)"),
    (r"size_(mean|sd|cv)|core|tem", "TEM (size histogram)"),
    (r"thickness", "profilometer or ellipsometer (thickness map)"),
    (r"roughness", "AFM or optical profilometer"),
    (r"xrd|crystal|phase", "XRD"),
    (r"viscos", "rheometer"),
    (r"conduct|resist", "four-point probe"),
    (r"yield|mass", "analytical balance"),
]


SPELL = {"um": "µm", "uL": "µL", "ul": "µL", "uM": "µM", "C": "°C", "pct": "%"}


def unit(key: str) -> str:
    for suf, u in UNITS:
        if key.endswith(suf):
            return u
    return ""


def label(key: str) -> str:
    """coating_gap_um -> coating gap (the unit goes in its own column)."""
    for suf, _ in UNITS:
        if key.endswith(suf):
            key = key[: -len(suf)]
            break
    return key.replace("_", " ")


def instrument(q: str) -> str:
    return next((name for pat, name in INSTRUMENTS if re.search(pat, q, re.I)), "")


def _equipment_from(text: str) -> list[str]:
    seen = []
    for pat, name in EQUIPMENT:
        if re.search(pat, text, re.I) and name not in seen:
            seen.append(name)
    return seen


def _materials_from(reagents: list[dict]) -> list[dict]:
    """The reagents the proposal carries (built-in systems); otherwise the agent lists them (robot.fill)."""
    return [{"name": r.get("name", ""), "amount": f"{r['conc_mM']} mM" if r.get("conc_mM") else "",
             "role": r.get("role", "")} for r in reagents if r.get("name")]


def build(s: dict, req: dict, robot: dict | None = None) -> dict:
    """The package for one robot request (a request = the chosen proposal + its recipe)."""
    pb = s.get("problem") or {}
    p = req.get("proposal") or {}
    rc = req.get("recipe") or {}
    steps = [re.sub(r"^\s*\d+[.)]\s*", "", x) for x in (rc.get("steps") or p.get("steps") or [])]
    knobs, fixed = pb.get("knobs") or {}, pb.get("fixed") or {}
    conds = p.get("conditions") or {}
    conditions = [{"name": k, "label": label(k), "value": v, "unit": unit(k),
                   "kind": "varied" if k in knobs else "fixed" if k in fixed else "set"}
                  for k, v in conds.items()]
    conditions.sort(key=lambda c: c["kind"] != "varied")

    text = " ".join([pb.get("method", ""), *steps])
    if rc.get("materials"):
        materials, mat_src = rc["materials"], "recipe"
    else:
        materials = _materials_from(p.get("reagents") or [])
        mat_src = "proposal" if materials else "none"
    if rc.get("equipment"):
        equipment, eq_src = list(rc["equipment"]), "recipe"
    else:
        equipment, eq_src = _equipment_from(text), "from the steps"

    targets = pb.get("targets") or {}
    pred = p.get("predicted") or {}
    qs = list(dict.fromkeys([*targets, *(p.get("measurements") or [])]))
    measurements = []
    for q in qs:
        b = pred.get(q) or {}
        t = targets.get(q) or {}
        measurements.append({"quantity": q, "label": label(q), "unit": SPELL.get(b.get("unit") or "", b.get("unit") or "") or unit(q),
                             "target": {k: t[k] for k in ("value", "min", "max") if k in t} or None,
                             "predicted": {k: b[k] for k in ("value", "low", "high") if k in b} or None,
                             "instrument": instrument(q)})
    tools = list(dict.fromkeys(m["instrument"] for m in measurements if m["instrument"]))
    accept = [f"{m['label']} inside the predicted band [{m['predicted']['low']:.3g}, {m['predicted']['high']:.3g}]"
              f" {m['unit']}".rstrip() for m in measurements if m["predicted"] and "low" in m["predicted"]]

    return {
        "format": FORMAT,
        "for": "a self-building lab (e.g. Self-Building Labs); it maps the package onto its own hardware",
        "study": req.get("study") or s.get("id"),
        "request": p.get("id"),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(req.get("at") or time.time())),
        "label": req.get("label", ""),
        "synthesis": {"title": rc.get("title") or pb.get("title") or "", "material": pb.get("material", ""),
                      "method": p.get("method") or pb.get("method", ""), "why": rc.get("why", "")},
        "conditions": conditions,
        "materials": materials, "materials_source": mat_src,
        "equipment": equipment, "equipment_source": eq_src,
        "tools": tools,
        "measurements": measurements,
        "steps": steps,
        "acceptance": [*accept, *(rc.get("checks") or [])],
        "risks": rc.get("risks") or [],
        "expected": rc.get("expected") or p.get("expected") or "",
        "platform": (robot or {}).get("name", "") or req.get("robot", ""),
        "returns": "measured values per quantity (with the run they came from) and the run log",
    }
