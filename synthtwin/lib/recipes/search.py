"""Rank library recipes for a Problem.

Called by synthtwin.lib.recipes.cli (search) and by anything assembling a
calibration set for the simulator. Filters by the problem's material and
allowed methods, then scores: having outcomes for the problem's target
quantities, closeness of those outcomes to the targets, closeness of the
recipe's conditions to the knob bounds, and the LeMat-Synth extraction score.
Every hit carries a one-line reason.
"""
from __future__ import annotations

from synthtwin.core.schemas import Problem, Recipe, Target

W_TARGETS = 2.0     # per target quantity the recipe has an outcome for
W_OUTCOME_CLOSE = 1.5   # how close that outcome sits to the target
W_KNOBS = 1.5       # conditions sit inside the problem's knob bounds
W_EXTRACTION = 0.5  # LeMat-Synth extraction confidence (normalised from 1-5)
EXTRACTION_MAX = 5.0


def _outcome(recipe: Recipe, quantity: str) -> float | None:
    hit = next((o for o in recipe.outcomes if o.quantity == quantity), None)
    return hit.value if hit else None


def target_closeness(target: Target, value: float) -> float:
    """0-1: inside a min/max range or near a point value (relative distance:
    on target 1, 100 % off 0)."""
    if target.value is not None:
        ref = abs(target.value) or 1.0
        return max(0.0, 1.0 - abs(value - target.value) / ref)
    lo, hi = target.min, target.max
    if lo is not None and hi is not None:
        if lo <= value <= hi:
            return 1.0
        span = (hi - lo) or 1.0
        return max(0.0, 1.0 - min(abs(value - lo), abs(value - hi)) / span)
    edge = lo if lo is not None else hi
    if edge is not None:
        return 1.0 if (edge == hi and value <= hi) or (edge == lo and value >= lo) else 0.0
    return 0.0


def knob_closeness(problem: Problem, recipe: Recipe) -> tuple[float, list[str]]:
    """Mean over the problem's knobs the recipe states, of 1 when inside the
    bounds, graded outside; unstated knobs earn nothing. Also returns one
    note per stated knob for the reason line."""
    scores, notes = [], []
    for name, (lo, hi) in problem.knobs.items():
        value = recipe.conditions.get(name)
        if value is None:
            continue
        span = max(hi - lo, 1e-9)
        if lo <= value <= hi:
            scores.append(1.0)
            notes.append(f"{name} {value:g} in [{lo:g}, {hi:g}]")
        else:
            gap = min(abs(value - lo), abs(value - hi)) / span
            scores.append(max(0.0, 1.0 - gap))
            where = "above" if value > hi else "below"
            notes.append(f"{name} {value:g} {where} [{lo:g}, {hi:g}]")
    if not scores:
        return 0.0, notes
    return sum(scores) / len(scores), notes


def _reason(recipe: Recipe, problem: Problem, notes: list[str]) -> str:
    bits = [recipe.material, recipe.method or "method not stated"]
    for quantity, target in problem.targets.items():
        value = _outcome(recipe, quantity)
        if value is not None:
            if target.value is not None:
                want = f"{target.value:g}"
            elif target.min is not None and target.max is not None:
                want = f"[{target.min:g}, {target.max:g}]"
            elif target.min is not None:
                want = f">= {target.min:g}"
            elif target.max is not None:
                want = f"<= {target.max:g}"
            else:
                want = "any"
            bits.append(f"{quantity} {value:g} vs {want}")
    outcomes_extra = [o.quantity for o in recipe.outcomes
                      if o.quantity not in problem.targets]
    if outcomes_extra:
        bits.append("also " + ", ".join(outcomes_extra))
    bits.extend(notes)
    if recipe.extraction_score is not None:
        bits.append(f"extraction {recipe.extraction_score:g}/5")
    if recipe.missing:
        bits.append(f"missing {len(recipe.missing)}")
    return "; ".join(bits)


def search(problem: Problem, library: list[Recipe], k: int = 20) -> list[tuple[Recipe, float, str]]:
    """Top-k (recipe, score, reason) for the problem: same material, an
    allowed method (any when the problem names none), ranked by the score
    above."""
    allowed = {m.strip().casefold() for m in problem.methods if m.strip()}
    hits: list[tuple[Recipe, float, str]] = []
    for recipe in library:
        if recipe.material.casefold() != problem.material.casefold():
            continue
        if allowed and recipe.method.casefold() not in allowed:
            continue
        target_score = close_score = 0.0
        for quantity, target in problem.targets.items():
            value = _outcome(recipe, quantity)
            if value is None:
                continue
            target_score += W_TARGETS * target.weight
            close_score += W_OUTCOME_CLOSE * target.weight * target_closeness(target, value)
        knob_score, notes = knob_closeness(problem, recipe)
        score = target_score + close_score + W_KNOBS * knob_score + (
            W_EXTRACTION * recipe.extraction_score / EXTRACTION_MAX
            if recipe.extraction_score is not None else 0.0)
        hits.append((recipe, score, _reason(recipe, problem, notes)))
    hits.sort(key=lambda hit: (-hit[1], hit[0].recipe_id))
    return hits[:k]
