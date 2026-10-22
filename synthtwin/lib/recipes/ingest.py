"""LeMat-Synth parquet rows -> Recipe library of colloidal / solution-made
nanoparticles.

Called by synthtwin.lib.recipes.cli (ingest) and tests. A row is kept when its
material name says nanoparticle/colloid (any material) and its method is a
solution route (physical deposition and lithography rows are dropped); fields
we cannot parse stay None/"" - nothing is guessed. pyarrow is imported lazily
so the module works without the `data` extra.
"""
from __future__ import annotations

import hashlib
import re

from synthtwin.lib.recipes.chem import JUNK_RE, canon_name, moles_mmol, parse_amount, parse_material, role_of
from synthtwin.lib.recipes.outcomes import parse_outcomes
from synthtwin.core.schemas import Outcome, Recipe, Reagent

COLUMNS = [
    "synthesized_material", "material_category", "synthesis_method",
    "structured_synthesis", "evaluation", "paper_title", "paper_doi",
    "paper_url", "paper_abstract", "paper_published_date",
]

# the material name must name a nano-object; bare 'particles'/'colloids'
# (colloidal crystals, emulsions, active matter) are not nanoparticle
# syntheses, and 'nanoporous', 'nanogap' etc. do not match either
_PARTICULATE_RE = re.compile(
    r"nanoparticle|nanocrystal|nanocluster|nanocolloid|nanosphere|nanorod|"
    r"nanowire|nanotube|nanostar|nanocube|nanocage|nanoflower|nanodot|"
    r"nanosheet|nanoplate|nanoframe|nanodendrite|nanobipyramid|nanotriangle|"
    r"nanostructure|nanomaterial|nanodispersion|quantum\s?dot|\bNPs?\b|\bQDs?\b",
    re.I)
# methods that make particles without a solution (dropped)
_PHYSICAL_RE = re.compile(
    r"pvd|cvd|\bald\b|atomic\s+layer|lithograph|sputter|evaporat|epitax|"
    r"molecular\s+beam|ablation|electrochem|electrodeposit|electrospin|plasma|"
    r"ion\s+implant|ball\s+mill|mechanochem|dealloy|spin.?\s?coat|electron\s+beam|"
    r"physical\s+vapor|chemical\s+vapor|thermal\s+deposition|implantation", re.I)
# methods that are solution routes, or at least not physical
_SOLUTION_RE = re.compile(
    r"precipitat|solution|sol-?gel|hydrothermal|solvothermal|sonochem|"
    r"microemulsion|polyol|reduction|chemical|microwave|combustion|"
    r"self-assembly|green|biosynth|colloidal|aqueous|other|solvotherm", re.I)
_LIQUID_UNITS = {"ml", "l", "ul", "mm", "m", "um", "mol/l", "mol l-1", "mmol/l"}

_METHOD_KEYWORDS = [
    ("hydrothermal", "hydrothermal"), ("solvothermal", "solvothermal"),
    ("sol-gel", "sol-gel"), ("sol-gel", "solgel"),
    ("microemulsion", "microemulsion"), ("sonochemical", "sonochem"),
    ("sonochemical", "ultrasonic"), ("microwave-assisted", "microwave"),
    ("polyol", "polyol"), ("precipitation", "precipitat"),
    ("combustion", "combustion"), ("self-assembly", "self-assembly"),
    ("solution synthesis", "solution"), ("solution synthesis", "aqueous"),
]

_ADD_RATE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|mL|uL|µL|μL|L)\s*/\s*min")

_FAMILY_ROLES = ("precursor", "reductant", "capping", "seed")
# a synthesis needs at least one of these besides solvent/other: rows with
# only 'SWCNT powder' or 'Au nanoparticles dispersed in water' are
# characterization or processing, not synthesis
_CHEM_ROLES = _FAMILY_ROLES + ("base", "acid")


def is_colloidal_np(row: dict) -> bool:
    """A row describes a solution-made nanoparticle synthesis: particulate
    material name, non-physical method, and solution evidence (a solution
    method or at least one liquid reagent)."""
    name = row.get("synthesized_material") or ""
    if not _PARTICULATE_RE.search(name):
        return False
    structured = row.get("structured_synthesis") or {}
    method = f"{row.get('synthesis_method') or ''} {structured.get('synthesis_method') or ''}"
    if _PHYSICAL_RE.search(method):
        return False
    if _SOLUTION_RE.search(method):
        return True
    for m in structured.get("starting_materials") or []:
        unit = (m.get("unit") or "").strip().replace("µ", "u").replace("μ", "u").lower()
        if unit in _LIQUID_UNITS:
            return True
    return False


def to_C(value, unit: str) -> float | None:
    """Structured step temperature + unit -> degrees C (K converted)."""
    if value is None:
        return None
    u = (unit or "").strip().upper().lstrip("°º∘ ")
    if u in ("C", "CELSIUS"):
        return float(value)
    if u == "K":
        return float(value) - 273.15
    return None


def to_min(value, unit: str) -> float | None:
    """Structured step duration + unit -> minutes (s, h, days converted)."""
    if value is None:
        return None
    u = (unit or "").strip().lower()
    factor = {"s": 1 / 60, "sec": 1 / 60, "min": 1.0, "h": 60.0, "hr": 60.0,
              "hour": 60.0, "hours": 60.0, "day": 1440.0, "days": 1440.0}.get(u)
    return float(value) * factor if factor else None


def canon_method(raw: str, reagents: list[Reagent], all_text: str) -> str:
    """Canonical method: seeded growth beats reductant names, reductant names
    beat the raw LeMat-Synth method keyword. Unknown stays 'other'."""
    roles = {r.role for r in reagents}
    names = " ".join(canon_name(r.name) for r in reagents)
    low = f"{raw or ''} {all_text} {names}".lower()
    if "seed" in roles or re.search(r"seed[-\s]?mediated", low) or (
            re.search(r"\bseeds?\b", low) and re.search(r"grow", low)):
        return "seeded growth"
    if "citrate" in names:
        return "citrate reduction"
    if "nabh4" in names or "kbh4" in names:
        return "borohydride reduction"
    if "ascorbic acid" in names:
        return "ascorbic acid reduction"
    if re.search(r"extract|biosynth|bio-?synthes|plant|bacteri|fungal|enzyme|\bgreen\b", low):
        return "green synthesis"
    if "reductant" in roles or re.search(r"\breduc", low):
        return "chemical reduction"
    for canonical, keyword in _METHOD_KEYWORDS:
        if keyword in (raw or "").lower():
            return canonical
    return "other"


def build_reagents(starting_materials: list[dict], material: str) -> list[Reagent]:
    """Starting-material entries -> Reagents with roles; glassware, substrates
    and gases are dropped, amounts become conc_mM / volume_ml when the units
    allow (molarity hidden in the purity field is used too)."""
    reagents = []
    for m in starting_materials or []:
        name = (m.get("name") or "").strip()
        if not name or JUNK_RE.search(name):
            continue
        conc, vol, amount_str = parse_amount(
            m.get("amount"), m.get("unit") or "", m.get("purity") or "")
        reagents.append(Reagent(
            role=role_of(name, material), name=name,
            conc_mM=conc, volume_ml=vol, amount=amount_str))
    return reagents


def _family_steps(steps: list[dict], family_names: set[str]) -> list[dict]:
    """Steps whose materials include a family reagent (precursor, reductant,
    capping or seed): that is where the chemistry happens."""
    out = []
    for step in steps:
        names = {canon_name(m.get("name") or "") for m in step.get("materials") or []}
        if names & family_names:
            out.append(step)
    return out


def _first_stated(getter, steps: list[dict], family: list[dict]):
    """First non-None value of getter(step), preferring chemistry steps and
    falling back to any step that states it."""
    for step in list(family) + list(steps):
        value = getter(step)
        if value is not None:
            return value
    return None


def extract_conditions(steps: list[dict], reagents: list[Reagent]) -> tuple[dict[str, float], list[str]]:
    """Steps + reagents -> canonical conditions and the missing-key list.
    temperature/time/stirring come from the chemistry steps (falling back to
    any step that states them); volumes and moles from the reagents."""
    conditions: dict[str, float] = {}
    family_names = {canon_name(r.name) for r in reagents if r.role in _FAMILY_ROLES}
    family = _family_steps(steps, family_names)

    def step_temp(step):
        c = step.get("conditions") or {}
        return to_C(c.get("temperature"), c.get("temp_unit") or "")

    def step_time(step):
        c = step.get("conditions") or {}
        return to_min(c.get("duration"), c.get("time_unit") or "")

    temp = _first_stated(step_temp, steps, family)
    if temp is not None:
        conditions["temperature_C"] = temp
    time = _first_stated(step_time, steps, family)
    if time is not None:
        conditions["time_min"] = time
    ph = _first_stated(lambda s: (s.get("conditions") or {}).get("ph"), steps, family)
    if ph is not None and 0.0 <= float(ph) <= 14.0:
        conditions["pH"] = float(ph)
    rpm = _first_stated(
        lambda s: (s.get("conditions") or {}).get("stirring_speed"), steps, family)
    if rpm is not None:
        conditions["stirring_rpm"] = float(rpm)

    for step in steps:  # addition rate stated in a description, e.g. "2 mL/min"
        m = _ADD_RATE_RE.search(step.get("description") or "")
        if m:
            conditions["addition_rate_ml_min"] = float(m.group(1)) * (
                1e-3 if m.group(2).lower() in ("ul", "µl", "μl") else
                1e3 if m.group(2) == "L" else 1.0)
            break

    volumes = [r.volume_ml for r in reagents if r.volume_ml is not None]
    if len(volumes) >= 2:
        conditions["total_volume_ml"] = round(sum(volumes), 4)

    moles: dict[str, float] = {}
    for r in reagents:
        mmol = moles_mmol(canon_name(r.name), r.name, r.conc_mM, r.volume_ml,
                          _split_amount(r.amount), _split_unit(r.amount))
        if mmol and r.role in ("precursor", "reductant", "capping"):
            moles[r.role] = moles.get(r.role, 0.0) + mmol
    total = conditions.get("total_volume_ml")
    for role in ("precursor", "reductant", "capping"):
        reagent = next((r for r in reagents if r.role == role), None)
        if reagent is None:
            continue
        if moles.get(role) and total:
            conditions[f"conc_{role}_mM"] = round(moles[role] / total * 1000.0, 4)
        elif reagent.conc_mM is not None:
            conditions[f"conc_{role}_mM"] = reagent.conc_mM
    if moles.get("reductant") and moles.get("precursor"):
        conditions["ratio_reductant_precursor"] = round(
            moles["reductant"] / moles["precursor"], 4)

    missing = [key for key in ("temperature_C", "time_min", "pH", "total_volume_ml")
               if key not in conditions]
    roles = {r.role for r in reagents}
    if "reductant" in roles and "precursor" in roles:
        missing += [key for key in ("ratio_reductant_precursor", "conc_precursor_mM",
                                    "conc_reductant_mM") if key not in conditions]
    return conditions, missing


def _split_amount(amount_str: str):
    m = re.match(r"([\d.]+)", amount_str or "")
    return float(m.group(1)) if m else None


def _split_unit(amount_str: str):
    m = re.match(r"[\d.]+\s*(\S+)", amount_str or "")
    return m.group(1) if m else ""


def _row_recipe(row: dict, paper_key: str) -> Recipe | None:
    """One parquet row -> Recipe (recipe_id set by the caller after
    deduplication), or None when the row is not a solution-made nanoparticle
    synthesis or the material does not parse."""
    if not is_colloidal_np(row):
        return None
    material = parse_material(row.get("synthesized_material") or "")
    if not material:
        return None
    structured = row.get("structured_synthesis") or {}
    steps = [s for s in (structured.get("steps") or []) if s]
    step_texts = [f"{s.get('action') or ''}. {s.get('description') or ''}" for s in steps]
    abstract = row.get("paper_abstract") or ""
    reagents = build_reagents(structured.get("starting_materials") or [], material)
    if not any(r.role in _CHEM_ROLES for r in reagents):
        return None  # no synthesis chemistry: characterization or processing row
    method = canon_method(
        f"{row.get('synthesis_method') or ''} {structured.get('synthesis_method') or ''}",
        reagents, " ".join(step_texts))
    texts = [("abstract", abstract), ("notes", structured.get("notes") or "")] + [
        (f"step {i + 1}", t) for i, t in enumerate(step_texts)]
    outcomes = parse_outcomes(texts)
    conditions, missing = extract_conditions(steps, reagents)
    scores = ((row.get("evaluation") or {}).get("scores") or {})
    return Recipe(
        recipe_id=f"lematsynth:{paper_key}:0",
        source="lematsynth",
        paper_doi=(row.get("paper_doi") or "").strip(),
        paper_title=(row.get("paper_title") or "").strip(),
        paper_url=(row.get("paper_url") or "").strip(),
        published=(row.get("paper_published_date") or "").strip(),
        material=material,
        method=method,
        reagents=reagents,
        conditions=conditions,
        steps=[f"{s.get('step_number', i + 1)}. {s.get('action') or ''}: "
               f"{s.get('description') or ''}".strip()[:240]
               for i, s in enumerate(steps)],
        outcomes=outcomes,
        missing=missing,
        extraction_score=scores.get("overall_score"),
    )


def _paper_key(row: dict) -> str:
    doi = (row.get("paper_doi") or "").strip()
    if doi:
        return doi
    return "sha1:" + hashlib.sha1((row.get("paper_title") or "").strip().encode()).hexdigest()[:12]


def lematsynth(paths, stats: dict | None = None) -> list[Recipe]:
    """Parquet path(s) -> deduplicated recipes. stats, when given, is filled
    with 'rows_read', 'kept' and 'duplicates' counts for the CLI."""
    import pyarrow.parquet as pq  # optional extra `data`

    recipes: list[Recipe] = []
    seen: set[tuple[str, str, str]] = set()
    counters: dict[str, int] = {}
    stats = stats if stats is not None else {}
    stats["rows_read"] = stats.get("rows_read", 0)
    stats["kept"] = stats.get("kept", 0)
    stats["duplicates"] = stats.get("duplicates", 0)
    for path in paths:
        pf = pq.ParquetFile(path)
        for batch in pf.iter_batches(batch_size=2048, columns=COLUMNS):
            for row in batch.to_pylist():
                stats["rows_read"] += 1
                key = _paper_key(row)
                recipe = _row_recipe(row, key)
                if recipe is None:
                    continue
                dedup_key = (key, recipe.material, recipe.method.casefold())
                if dedup_key in seen:  # same paper, material and method
                    stats["duplicates"] += 1
                    continue
                seen.add(dedup_key)
                recipe.recipe_id = f"lematsynth:{key}:{counters.get(key, 0)}"
                counters[key] = counters.get(key, 0) + 1
                recipes.append(recipe)
                stats["kept"] += 1
    return recipes
