"""Turn optimiser Candidates into robot-ready Proposals.

propose.make keeps the novel, robot-feasible candidates and writes each one as
concrete steps in robot terms: which stock solutions to dispense at what volume
for the target concentrations, heating, stirring, reductant addition rate and
ageing, then the measurements (UV-Vis 300-900 nm, DLS z-average + PDI) with the
predicted lspr_nm / dls_z_nm to compare against. Controls are the best-matching
known library recipe and a repeat of it. Called by run.main.

Stock strings on the RobotProfile are "<name> <conc> mM (<role>)"; a bare
"<name>" is a pure solvent. Names are matched case-insensitively against the
reagent names the library uses for this family.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Callable

from synthtwin.core.schemas import Candidate, Novelty, Problem, Proposal, Recipe, RobotProfile

STOCK_RE = re.compile(r"^(?P<name>.+?)\s+(?P<conc>\d+(?:\.\d+)?)\s*mM\s*\((?P<role>\w+)\)$")

DEFAULT_STIRRING_RPM = 600.0
DEFAULT_ADDITION_RATE_ML_MIN = 1.0
MIN_FAMILY_FOR_COVERAGE = 3      # fewer family recipes than this -> "thin"
EXACT_MATCH_DISTANCE = 0.0

NoveltyFn = Callable[[Candidate, list[Recipe]], Novelty]


def make(
    problem: Problem,
    candidates: list[Candidate],
    novelty_fn: NoveltyFn | None,
    robot: RobotProfile,
    library: list[Recipe],
) -> list[Proposal]:
    """-> up to problem.n_proposals Proposals, best candidate first.

    A candidate is dropped (not fatal) when it repeats known work, needs
    anything outside the RobotProfile, or its stocks cannot reach the target
    concentrations."""
    stocks = parse_stocks(robot)
    names = family_reagent_names(library, problem)
    proposals: list[Proposal] = []
    for cand in candidates:
        if len(proposals) >= problem.n_proposals:
            break
        novel = (novelty_fn or exact_match_novelty)(cand, library)
        if not novel.novel:
            continue
        feas = feasibility(cand, robot, stocks, names)
        if not feas.ok:
            continue
        control = nearest_recipe(cand, library)
        proposals.append(
            Proposal(
                proposal_id=f"{problem.problem_id}-p{len(proposals) + 1:02d}",
                problem_id=problem.problem_id,
                candidate=cand,
                novelty=novel,
                steps=feas.steps,
                measurements=measurements(robot),
                controls=controls(control),
                expected=expected(cand),
                risks=risks(cand, novel, feas, control),
            )
        )
    return proposals


# --------------------------------------------------------------------- stocks
def parse_stocks(robot: RobotProfile) -> dict[str, list[tuple[str, float | None]]]:
    """RobotProfile.reagents -> {role: [(name, conc_mM)]; None = pure solvent}."""
    stocks: dict[str, list[tuple[str, float | None]]] = {}
    for entry in robot.reagents:
        m = STOCK_RE.match(entry.strip())
        if m:
            stocks.setdefault(m["role"].lower(), []).append((m["name"], float(m["conc"])))
            continue
        stocks.setdefault("solvent", []).append((entry.strip(), None))
    return stocks


def family_reagent_names(library: list[Recipe], problem: Problem) -> dict[str, str]:
    """Most common reagent name per role among the library recipes of the family."""
    counts: dict[str, Counter[str]] = {}
    for r in library:
        if r.material != problem.material:
            continue
        if problem.methods and r.method not in problem.methods:
            continue
        for rg in r.reagents:
            if rg.name:
                counts.setdefault(rg.role, Counter())[rg.name] += 1
    return {role: c.most_common(1)[0][0] for role, c in counts.items()}


# ---------------------------------------------------------------- feasibility
def feasibility(
    cand: Candidate,
    robot: RobotProfile,
    stocks: dict[str, list[tuple[str, float | None]]],
    names: dict[str, str],
) -> Feasibility:
    """Check a candidate against the robot and write its dispense/heat/stir steps."""
    c = cand.conditions
    total = c.get("total_volume_ml", 0.0)
    temp = c.get("temperature_C", 0.0)
    reasons: list[str] = []
    if not (robot.temperature_C[0] <= temp <= robot.temperature_C[1]):
        reasons.append(f"temperature {temp:g} C outside robot range "
                       f"{robot.temperature_C[0]:g}-{robot.temperature_C[1]:g} C")
    if not (robot.volume_ml[0] <= total <= robot.volume_ml[1]):
        reasons.append(f"total volume {total:g} mL outside robot range "
                       f"{robot.volume_ml[0]:g}-{robot.volume_ml[1]:g} mL")

    targets = solute_targets(c)
    lines: list[str] = []
    role_vols: dict[str, float] = {}
    used = 0.0
    for role, conc, stock_name, stock_conc in resolved_solutes(targets, stocks, names):
        if conc is None:
            reasons.append(f"cannot reach the target concentration for role '{role}' "
                           f"({names.get(role, stock_name)}; best stock {stock_conc:g} mM)")
            continue
        vol = total * conc / stock_conc
        if not (robot.volume_ml[0] <= vol <= robot.volume_ml[1]):
            reasons.append(
                f"{role} needs {vol:.2f} mL of {stock_name} ({stock_conc:g} mM stock) for "
                f"{conc:g} mM x {total:g} mL; outside robot volume range"
            )
            continue
        lines.append(f"Dispense {vol:.2f} mL of {stock_name} stock ({stock_conc:g} mM) "
                     f"-> {conc:.3g} mM {role} in the final {total:g} mL")
        role_vols[role] = vol
        used += vol
    if total and used > total:
        reasons.append(f"stock volumes ({used:.2f} mL) exceed the total volume ({total:g} mL)")
    if reasons:
        return Feasibility(False, reasons, [])

    solvent = (stocks.get("solvent") or [("water", None)])[0][0]
    make_up = total - used
    steps = list(lines)
    if make_up >= robot.volume_ml[0]:
        steps.append(f"Dispense {make_up:.2f} mL of {solvent} to make up {total:g} mL total")
    rpm = c.get("stirring_rpm", DEFAULT_STIRRING_RPM)
    rate = c.get("addition_rate_ml_min", DEFAULT_ADDITION_RATE_ML_MIN)
    assumed = [
        label for key, label in [
            ("stirring_rpm", "stirring at 600 rpm"),
            ("addition_rate_ml_min", "reductant addition 1.0 mL/min"),
            ("time_min", "ageing 30 min"),
        ] if key not in c
    ]
    steps.append(f"Heat to {temp:.0f} C with stirring at {rpm:.0f} rpm")
    if "reductant" in role_vols:
        steps.append(f"Add the reductant stock ({role_vols['reductant']:.2f} mL) at "
                     f"{rate:.2f} mL/min once at temperature")
    steps.append(f"Age at {temp:.0f} C for {c.get('time_min', 30.0):.0f} min, "
                 "then cool to room temperature")
    steps.append("Transfer an aliquot for UV-Vis (300-900 nm) and for DLS "
                 "(z-average, PDI); dilute if the absorbance saturates")
    return Feasibility(True, [], steps, assumed)


class Feasibility:
    """Result of checking one candidate against the robot."""

    def __init__(self, ok: bool, reasons: list[str], steps: list[str],
                 assumed: list[str] | None = None) -> None:
        self.ok = ok
        self.reasons = reasons
        self.steps = steps
        self.assumed = assumed or []


def solute_targets(c: dict[str, float]) -> list[tuple[str, float | None]]:
    """Conditions -> [(role, target final concentration in mM)]."""
    out: list[tuple[str, float | None]] = []
    precursor = c.get("conc_precursor_mM")
    if precursor is not None:
        out.append(("precursor", precursor))
    ratio = c.get("ratio_reductant_precursor")
    if precursor is not None and ratio is not None:
        out.append(("reductant", precursor * ratio))
    if "conc_capping_mM" in c:
        out.append(("capping", c["conc_capping_mM"]))
    elif "ratio_capping_precursor" in c and precursor is not None:
        out.append(("capping", precursor * c["ratio_capping_precursor"]))
    return out


def resolved_solutes(
    targets: list[tuple[str, float | None]],
    stocks: dict[str, list[tuple[str, float | None]]],
    names: dict[str, str],
) -> list[tuple[str, float | None, str, float]]:
    """Match each (role, conc) to a stock by role and reagent name."""
    resolved = []
    for role, conc in targets:
        candidates = [
            (name, sc) for name, sc in stocks.get(role, [])
            if sc is not None and name.lower() == names.get(role, name).lower()
        ] or [(name, sc) for name, sc in stocks.get(role, []) if sc is not None]
        if not candidates or conc is None:
            resolved.append((role, None, names.get(role, role), 0.0))
            continue
        name, stock_conc = max(candidates, key=lambda t: t[1])  # most concentrated stock
        if stock_conc < conc:
            resolved.append((role, None, name, stock_conc))
            continue
        resolved.append((role, conc, name, stock_conc))
    return resolved


# -------------------------------------------------------------- novelty, controls
def exact_match_novelty(cand: Candidate, library: list[Recipe]) -> Novelty:
    """Built-in fallback: only an exact conditions match counts as known."""
    fam = [r for r in library if _same_family(r, cand)]
    for r in fam:
        if set(r.conditions) == set(cand.conditions) and all(
            abs(r.conditions[k] - cand.conditions[k]) < 1e-9 for k in cand.conditions
        ):
            return Novelty(
                novel=False, nearest_recipe_id=r.recipe_id, distance=EXACT_MATCH_DISTANCE,
                coverage=_coverage(fam),
                reason="conditions match a known library recipe exactly",
            )
    nearest = min(fam, key=lambda r: _distance(r, cand), default=None)
    return Novelty(
        novel=True,
        nearest_recipe_id=nearest.recipe_id if nearest else None,
        distance=_distance(nearest, cand) if nearest else None,
        coverage=_coverage(fam),
        reason="no exact match in the library (built-in exact-match check)",
    )


def _same_family(recipe: Recipe, cand: Candidate) -> bool:
    return recipe.method == cand.method if cand.method else True


def _coverage(fam: list[Recipe]) -> str:
    return "ok" if len(fam) >= MIN_FAMILY_FOR_COVERAGE else "thin"


def _distance(recipe: Recipe, cand: Candidate) -> float:
    """Mean normalised |difference| over shared conditions keys (0 = identical)."""
    shared = [k for k in recipe.conditions if k in cand.conditions]
    if not shared:
        return 1.0
    return sum(
        abs(recipe.conditions[k] - cand.conditions[k]) / max(abs(recipe.conditions[k]), 1e-9)
        for k in shared
    ) / len(shared)


def nearest_recipe(cand: Candidate, library: list[Recipe]) -> Recipe | None:
    fam = [r for r in library if _same_family(r, cand)]
    return min(fam, key=lambda r: _distance(r, cand), default=None)


def controls(control: Recipe | None) -> list[str]:
    if control is None:
        return ["no library recipe to compare against: run the proposal alone"]
    one = "; ".join(control.steps[:2]) if control.steps else control.recipe_id
    return [
        f"control: best-matching known recipe {control.recipe_id} ({one})",
        f"repeat: run {control.recipe_id} a second time to measure robot repeatability",
    ]


def measurements(robot: RobotProfile) -> list[str]:
    text = " ".join(robot.instruments).lower()
    out = []
    if "uv-vis" in text or "uvvis" in text:
        out.append("UV-Vis 300-900 nm (lspr peak position and width)")
    if "dls" in text:
        out.append("DLS z-average + PDI")
    return out or ["UV-Vis 300-900 nm", "DLS z-average + PDI"]


def expected(cand: Candidate) -> str:
    parts = []
    for q in sorted(cand.predicted):
        b = cand.predicted[q]
        unit = f" {b.unit}" if b.unit else ""
        parts.append(f"{q} = {b.value:.3g}{unit} (band {b.low:.3g}-{b.high:.3g})")
    return "; ".join(parts) + ". Compare the measured lspr_nm and dls_z_nm with these bands."


def risks(cand: Candidate, novel: Novelty, feas: Feasibility, control: Recipe | None) -> list[str]:
    out = list(cand.notes)
    if novel.coverage == "thin":
        out.append("library coverage is thin near this recipe; 'novel' may just mean 'unmapped'")
    if not cand.in_validated_region:
        out.append("outside the validated simulator region: treat predictions as exploratory")
    if control is None:
        out.append("no known recipe in the family to control against")
    if feas.assumed:
        out.append("assumed " + " and ".join(feas.assumed)
                   + " (not fixed by the problem); volumes rounded to 0.01 mL")
    return out
