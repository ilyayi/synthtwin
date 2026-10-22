"""Novelty check of a candidate recipe against the library.

Called by synthtwin.lib.design (propose) before any candidate becomes a proposal,
and by synthtwin.lib.recipes.cli tests. The comparison family is the same
material + method, minus recipes that state a different reductant or capping
agent (different chemistry, not a repeat). distance is the max over
conditions of |candidate - library| / tolerance for keys known on both sides;
novel means the nearest neighbour stands at distance >= 1. Fewer than 3
family recipes is 'thin' coverage - reported, never called novel.
"""
from __future__ import annotations

from synthtwin.lib.recipes.chem import canon_name
from synthtwin.core.schemas import Novelty, Recipe

# condition key -> ("rel", fraction of the larger value) | ("abs", units).
# Keys not listed get their tolerance by prefix: ratio_* and conc_* are 20 %
# relative, everything else 50 % relative.
DEFAULT_TOL: dict[str, tuple[str, float]] = {
    "temperature_C": ("abs", 5.0),
    "pH": ("abs", 0.5),
    "time_min": ("rel", 0.5),
    "addition_rate_ml_min": ("rel", 0.5),
    "total_volume_ml": ("rel", 0.5),
    "stirring_rpm": ("rel", 0.5),
}
PREFIX_TOL = {"ratio_": ("rel", 0.2), "conc_": ("rel", 0.2)}
FALLBACK_TOL = ("rel", 0.5)
MIN_COVERAGE = 3  # family recipes below which coverage is thin
_VETING_ROLES = ("reductant", "capping")


def tolerance_for(key: str, tol: dict | None = None) -> tuple[str, float]:
    """Tolerance of one condition key, with a caller's partial override."""
    if tol and key in tol:
        return tol[key]
    if key in DEFAULT_TOL:
        return DEFAULT_TOL[key]
    for prefix, fallback in PREFIX_TOL.items():
        if key.startswith(prefix):
            return fallback
    return FALLBACK_TOL


def _role_names(recipe: Recipe, role: str) -> set[str]:
    return {canon_name(r.name) for r in recipe.reagents if r.role == role}


def _same_family(candidate: Recipe, recipe: Recipe) -> bool:
    if recipe.material.strip().casefold() != candidate.material.strip().casefold():
        return False
    if (candidate.method and recipe.method
            and candidate.method.strip().casefold() != recipe.method.strip().casefold()):
        return False
    for role in _VETING_ROLES:  # a stated different reductant/capping = other work
        mine = _role_names(candidate, role)
        theirs = _role_names(recipe, role)
        if mine and theirs and not (mine & theirs):
            return False
    return True


def _knob_distance(name: str, cand: float, lib: float, tol: dict | None) -> float:
    kind, size = tolerance_for(name, tol)
    if kind == "abs":
        return abs(cand - lib) / size
    ref = max(abs(cand), abs(lib))
    return 0.0 if ref == 0 else abs(cand - lib) / (size * ref)


def _nearest(candidate: Recipe, pool: list[Recipe], tol: dict | None = None
             ) -> tuple[Recipe, float, str] | None:
    """(recipe, distance, one-line condition detail) for the closest pool
    recipe. Recipes sharing at least one condition with the candidate always
    outrank condition-less ones (those are distance 0 only because nothing is
    recorded: they cannot establish a real match)."""
    shared: list[tuple[Recipe, float, str]] = []
    keyless: list[Recipe] = []
    for recipe in sorted(pool, key=lambda r: r.recipe_id):
        dists, detail = [], []
        for name in sorted(set(candidate.conditions) & set(recipe.conditions)):
            d = _knob_distance(name, candidate.conditions[name],
                               recipe.conditions[name], tol)
            dists.append(d)
            detail.append(f"{name} {candidate.conditions[name]:g} vs "
                          f"{recipe.conditions[name]:g} (d {d:.2f})")
        if dists:
            shared.append((recipe, max(dists), "; ".join(detail)))
        else:
            keyless.append(recipe)
    if shared:
        return min(shared, key=lambda hit: hit[1])
    if keyless:
        return keyless[0], 0.0, "no shared conditions recorded"
    return None


def check(candidate: Recipe | dict, library: list[Recipe], tol: dict | None = None) -> Novelty:
    """Novelty of a candidate given as a Recipe or Recipe fields (a dict with
    at least 'material'; keys must be Recipe fields). tol partially overrides
    the default tolerances per condition key, as ('rel', fraction) or
    ('abs', units)."""
    if isinstance(candidate, Recipe):
        cand = candidate
    else:
        cand = Recipe.model_validate(
            {"recipe_id": "candidate", "source": "candidate", **candidate})

    pool = [r for r in library if _same_family(cand, r)]
    nearest = _nearest(cand, pool, tol)
    family = f"{cand.material} + {cand.method or 'any method'}"
    if len(pool) < MIN_COVERAGE:
        return Novelty(
            novel=False,
            nearest_recipe_id=nearest[0].recipe_id if nearest else None,
            distance=nearest[1] if nearest else None,
            coverage="thin",
            reason=(f"thin coverage: no {family} recipes in the library at all"
                    if not pool else
                    f"thin coverage: only {len(pool)} {family} recipe(s) in "
                    "the library - a match cannot be ruled out"),
        )
    if nearest is None:
        return Novelty(
            novel=True, coverage="ok",
            reason=f"{len(pool)} {family} recipes, none comparable on conditions")
    recipe, distance, detail = nearest
    if distance >= 1.0:
        return Novelty(
            novel=True, nearest_recipe_id=recipe.recipe_id, distance=distance,
            coverage="ok",
            reason=f"nearest is {recipe.recipe_id} at distance {distance:.2f} ({detail})")
    return Novelty(
        novel=False, nearest_recipe_id=recipe.recipe_id, distance=distance,
        coverage="ok",
        reason=f"matches {recipe.recipe_id} within tolerance "
        f"(distance {distance:.2f}: {detail})")
