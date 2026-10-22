"""Calibrate the simulator on the library recipes of one (material, method) family.

calibrate.family picks the library recipes that match the problem's material and
methods, have measured outcomes and enough conditions to run the predictor, asks
the predictor to calibrate on each, merges the per-recipe calibration dicts by
median and measures the family spread (median relative deviation of the
calibrated predictor on those recipes). n = 0 means "uncalibrated": no
calibration params and wider bands (band_factor below); run.py says how much.

Called by run.main; tests call it with the stub predictor.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from synthtwin.core.schemas import Problem, Recipe

# a recipe needs at least this many reported conditions (including temperature_C)
# before the simulator can be calibrated on it
MIN_FAMILY_CONDITIONS = 2

# no family recipes -> no calibration; widen every predicted band by this factor
UNCALIBRATED_BAND_FACTOR = 2.5

# calibrated but no spread measurable (predictor returned no matching quantity)
NO_SPREAD_BAND_FACTOR = 1.5


@dataclass
class Calibration:
    """Result of family(): what optimize.run needs to know about the simulator."""
    params: dict[str, Any] = field(default_factory=dict)  # passed as params["calibration"]
    n: int = 0                                          # recipes calibrated on
    spread: float | None = None                         # median relative deviation on the family
    status: str = "uncalibrated"                        # "calibrated" | "uncalibrated"
    band_factor: float = UNCALIBRATED_BAND_FACTOR       # multiply band half-widths by this
    recipe_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def family(predictor: Any, library: list[Recipe], problem: Problem) -> Calibration:
    """ predictor (module with predict + calibrate) + library + problem -> Calibration."""
    fam = [
        r for r in library
        if r.material == problem.material
        and (not problem.methods or r.method in problem.methods)
        and r.outcomes
        and len(r.conditions) >= MIN_FAMILY_CONDITIONS
        and "temperature_C" in r.conditions
    ]
    if not fam:
        methods = problem.methods or [r.method for r in library if r.material == problem.material]
        return Calibration(
            status="uncalibrated",
            notes=[
                f"no library recipes for {problem.material} / {', '.join(m or '(any)' for m in methods)} "
                f"with measured outcomes and >= {MIN_FAMILY_CONDITIONS} conditions (incl. temperature_C); "
                f"running uncalibrated and widening bands x{UNCALIBRATED_BAND_FACTOR:g}"
            ],
        )

    per_recipe: list[dict[str, Any]] = []
    for r in fam:
        params = _params(r)
        try:
            cal = predictor.calibrate(params, [o for o in r.outcomes])
        except Exception:  # a recipe the predictor cannot use is skipped, not fatal
            continue
        if isinstance(cal, dict) and cal:
            per_recipe.append({k: v for k, v in cal.items() if isinstance(v, (int, float))})
    merged = _merge(per_recipe)
    if not merged:
        return Calibration(
            n=len(fam), recipe_ids=[r.recipe_id for r in fam], status="uncalibrated",
            notes=["predictor returned no usable calibration for any family recipe; "
                   f"bands widened x{UNCALIBRATED_BAND_FACTOR:g}"],
        )

    cal = Calibration(
        params=merged, n=len(fam), status="calibrated",
        recipe_ids=[r.recipe_id for r in fam],
    )
    cal.spread = _spread(predictor, fam, problem, merged)
    if cal.spread is None:
        cal.band_factor = NO_SPREAD_BAND_FACTOR
        cal.notes.append(
            f"predictor reports none of the target quantities on the family; "
            f"bands widened x{NO_SPREAD_BAND_FACTOR:g}"
        )
    else:
        cal.band_factor = 1.0 + cal.spread
        cal.notes.append(
            f"median relative deviation on {len(fam)} family recipes: {cal.spread:.1%}; "
            f"bands widened x{cal.band_factor:.2f}"
        )
    return cal


def _params(recipe: Recipe) -> dict[str, Any]:
    return {
        "material": recipe.material,
        "method": recipe.method,
        "conditions": dict(recipe.conditions),
        "reagents": [r.model_dump() for r in recipe.reagents],
    }


def _merge(per_recipe: list[dict[str, Any]]) -> dict[str, Any]:
    """One calibration dict from many recipes: median per numeric key."""
    keys = sorted({k for cal in per_recipe for k in cal})
    return {k: statistics.median([cal[k] for cal in per_recipe if k in cal]) for k in keys}


def _spread(predictor: Any, fam: list[Recipe], problem: Problem, merged: dict[str, Any]) -> float | None:
    """Median over recipes of the median relative |predicted - measured| / measured,
    over the problem's target quantities (falling back to every matched quantity)."""
    wanted = set(problem.targets)
    per_recipe_err: list[float] = []
    for r in fam:
        params = _params(r)
        params["calibration"] = merged
        pred = predictor.predict(params)
        rels_all: list[float] = []
        rels_wanted: list[float] = []
        for o in r.outcomes:
            if o.quantity not in pred or not o.value:
                continue
            rel = abs(float(pred[o.quantity]["value"]) - o.value) / abs(o.value)
            rels_all.append(rel)
            if o.quantity in wanted:
                rels_wanted.append(rel)
        rels = rels_wanted or rels_all
        if rels:
            per_recipe_err.append(statistics.median(rels))
    if not per_recipe_err:
        return None
    return statistics.median(per_recipe_err)
