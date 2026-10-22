"""Load and validate a design Problem from yaml.

Called by the CLI (synthtwin-design) and the tests. Knob keys must be canonical
conditions keys and targets must name known outcome quantities, so a typo fails
here with one clear message instead of deep inside the optimiser.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from synthtwin.core.schemas import Problem, Target

# keys any recipe condition may use (schemas.py, Recipe.conditions comment)
CANONICAL_CONDITIONS = {
    "temperature_C", "time_min", "pH", "total_volume_ml",
    "addition_rate_ml_min", "stirring_rpm",
    "seed_d_nm", "n_injections", "injection_interval_min",   # seeded growth (synthtwin.lib.np)
}
_RATIO_KEY = re.compile(r"^ratio_[a-z0-9]+_[a-z0-9]+$")      # e.g. ratio_reductant_precursor
_CONC_KEY = re.compile(r"^conc_[a-z0-9]+_mM$")               # e.g. conc_precursor_mM

# outcome quantities the pipeline knows how to talk about (schemas.py, Outcome)
KNOWN_QUANTITIES = {
    "size_mean_nm", "size_sd_nm", "size_cv_pct",
    "lspr_nm", "lspr_fwhm_nm", "dls_z_nm", "dls_pdi", "t50_K",
}


def is_condition_key(key: str) -> bool:
    """True if key is a canonical conditions key (exact or ratio_/conc_ pattern)."""
    return key in CANONICAL_CONDITIONS or bool(_RATIO_KEY.match(key)) or bool(_CONC_KEY.match(key))


def is_known_quantity(quantity: str) -> bool:
    return quantity in KNOWN_QUANTITIES


def validate(problem: Problem) -> Problem:
    """Raise ValueError listing every problem at once; return the problem if fine."""
    errors: list[str] = []
    if not problem.material:
        errors.append("material is empty")
    if not problem.knobs:
        errors.append("no knobs: the optimiser needs at least one conditions key to vary")
    for key, (lo, hi) in problem.knobs.items():
        if not is_condition_key(key):
            errors.append(f"knob '{key}' is not a canonical conditions key "
                          "(temperature_C, time_min, ratio_reductant_precursor, ...)")
        if lo >= hi:
            errors.append(f"knob '{key}' has empty range [{lo}, {hi}]")
    for key in problem.fixed:
        if not is_condition_key(key):
            errors.append(f"fixed condition '{key}' is not a canonical conditions key")
    for key in set(problem.knobs) & set(problem.fixed):
        errors.append(f"'{key}' is both a knob and fixed")
    if not problem.targets:
        errors.append("no targets: state at least one outcome quantity to aim for")
    for quantity, target in problem.targets.items():
        if not is_known_quantity(quantity):
            errors.append(f"target '{quantity}' is not a known quantity "
                          f"(one of {', '.join(sorted(KNOWN_QUANTITIES))})")
        if target.value is None and target.min is None and target.max is None:
            errors.append(f"target '{quantity}' has no value, min or max")
        if target.weight <= 0:
            errors.append(f"target '{quantity}' weight must be > 0")
    if problem.n_proposals < 1:
        errors.append("n_proposals must be >= 1")
    if errors:
        raise ValueError("invalid problem:\n  - " + "\n  - ".join(errors))
    return problem


def load(path: str | Path) -> Problem:
    """yaml file -> validated Problem."""
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a yaml mapping at the top level")
    data.setdefault("text", str(data.get("text", "")))
    try:
        problem = Problem(**data)
    except Exception as exc:  # pydantic dumps every field error already
        raise ValueError(f"{path}: {exc}") from exc
    return validate(problem)
