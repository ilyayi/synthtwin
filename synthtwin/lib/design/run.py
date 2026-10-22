"""synthtwin-design CLI: problem yaml -> report.md + proposals.json.

Loads the problem, the recipe library, the robot profile and the predictor
module, calibrates on the library family, optimises, checks novelty and writes
robot-ready proposals. Recipe search and novelty come from synthtwin.lib.recipes
when that package is installed; otherwise a built-in filter (material+method)
and an exact-match novelty check are used and the report says so.

Usage:

  synthtwin-design problem.yaml --library recipes.jsonl --robot robot.yaml \
      --predictor package.module [--validated v.json] --out DIR
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from synthtwin.lib.design import calibrate as calibrate_mod
from synthtwin.lib.design import optimize, propose
from synthtwin.lib.design.problem import load as load_problem
from synthtwin.core.schemas import Problem, Recipe, RobotProfile


def load_predictor(spec: str) -> Any:
    """'package.module' -> module with predict() and calibrate()."""
    module = importlib.import_module(spec)
    for attr in ("predict", "calibrate"):
        if not callable(getattr(module, attr, None)):
            raise ImportError(f"predictor module {spec!r} has no callable {attr}()")
    return module


def load_library(path: str | Path) -> list[Recipe]:
    lines = [l for l in Path(path).read_text().splitlines() if l.strip()]
    return [Recipe.model_validate_json(l) for l in lines]


def recipe_search(library: list[Recipe], problem: Problem) -> tuple[list[Recipe], str]:
    """synthtwin.lib.recipes.search when present, else the built-in material+method filter."""
    try:
        from synthtwin.lib.recipes import search as recipes_search  # type: ignore
        hits = recipes_search.search(problem, library, k=len(library))
        return [r for r, _score, _reason in hits], "synthtwin.lib.recipes.search"
    except ImportError:
        return [
            r for r in library
            if r.material == problem.material
            and (not problem.methods or r.method in problem.methods)
        ], "built-in filter (synthtwin.lib.recipes not installed)"


def novelty_fn() -> tuple[Any, str]:
    """synthtwin.lib.recipes.novelty.check when present, else the exact-match fallback."""
    try:
        from synthtwin.lib.recipes import novelty as recipes_novelty  # type: ignore
        return recipes_novelty.check, "synthtwin.lib.recipes.novelty.check"
    except ImportError:
        return propose.exact_match_novelty, "built-in exact-match check (synthtwin.lib.recipes not installed)"


def resolve_method(problem: Problem, cal: calibrate_mod.Calibration, library: list[Recipe]) -> list[str]:
    """Empty methods -> the most common method among the family recipes."""
    if problem.methods:
        return problem.methods
    counts = Counter(
        r.method for r in library
        if r.recipe_id in set(cal.recipe_ids) and r.method
    )
    return [counts.most_common(1)[0][0]] if counts else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="synthtwin-design")
    parser.add_argument("problem", help="problem yaml (see examples/problem.yaml)")
    parser.add_argument("--library", required=True, help="recipes.jsonl")
    parser.add_argument("--robot", required=True, help="robot profile yaml")
    parser.add_argument("--predictor", required=True, help="module with predict() + calibrate()")
    parser.add_argument("--validated", help="validated.json {method: {knob: [lo, hi]}}")
    parser.add_argument("--out", default="out", help="output directory (report.md, proposals.json)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-eval", type=int, default=80)
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    try:
        problem = load_problem(args.problem)
    except ValueError as exc:
        print(f"invalid problem: {exc}", file=sys.stderr)
        (out / "report.md").write_text(f"# Invalid problem\n\n{exc}\n")
        return 1

    library = load_library(args.library)
    robot = RobotProfile(**yaml.safe_load(Path(args.robot).read_text()))
    try:
        predictor = load_predictor(args.predictor)
    except (ImportError, AttributeError) as exc:
        print(f"cannot load predictor: {exc}", file=sys.stderr)
        return 1

    assumptions: list[str] = []
    family, search_used = recipe_search(library, problem)
    check_novelty, novelty_used = novelty_fn()
    if novelty_used.startswith("synthtwin.lib.recipes"):
        _check = check_novelty

        def check_novelty(cand, lib):
            # recipes.novelty takes Recipe fields; a Candidate lacks the material
            return _check({"recipe_id": "candidate", "source": "manual",
                           "material": problem.material, "method": cand.method,
                           "reagents": cand.reagents, "conditions": cand.conditions}, lib)
    assumptions.append(f"recipe search: {search_used}")
    assumptions.append(f"novelty check: {novelty_used}")

    cal = calibrate_mod.family(predictor, family, problem)
    methods = resolve_method(problem, cal, library)
    if methods and methods != problem.methods:
        assumptions.append(f"problem lists no method; using '{methods[0]}' "
                           "(most common among the family recipes)")
        problem = problem.model_copy(update={"methods": methods})

    validated = json.loads(Path(args.validated).read_text()) if args.validated else None
    candidates = optimize.run(
        problem, predictor, cal, seed=args.seed, n_eval=args.n_eval, validated=validated,
    )
    proposals = propose.make(problem, candidates, check_novelty, robot, library)
    assumptions.extend(cal.notes)

    (out / "proposals.json").write_text(
        json.dumps(
            {
                "problem_id": problem.problem_id,
                "calibration": {
                    "status": cal.status, "n": cal.n, "spread": cal.spread,
                    "params": cal.params, "band_factor": cal.band_factor,
                },
                "proposals": [p.model_dump(mode="json") for p in proposals],
            },
            indent=2,
        )
        + "\n"
    )
    (out / "report.md").write_text(
        report(problem, family, cal, candidates, proposals, robot, assumptions)
    )
    print(f"{len(proposals)} proposal(s) -> {out / 'proposals.json'} (report: {out / 'report.md'})")
    if not proposals:
        print("no proposals: nothing novel and robot-feasible came out of the search; "
              "see report.md", file=sys.stderr)
        return 1
    return 0


# ------------------------------------------------------------------ report md
def report(
    problem: Problem,
    family: list[Recipe],
    cal: calibrate_mod.Calibration,
    candidates: list,
    proposals: list,
    robot: RobotProfile,
    assumptions: list[str],
) -> str:
    lines = [f"# SynthTwin design: {problem.problem_id}", ""]
    lines += ["## Problem", "", problem.text.strip(), ""]
    lines += [
        f"- material: **{problem.material}**, method: "
        f"{problem.methods[0] if problem.methods else '(any)'}",
        "- targets: "
        + "; ".join(
            f"{q} = " + "/".join(
                s for s in (
                    f"{t.value:g}" if t.value is not None else "",
                    f">= {t.min:g}" if t.min is not None else "",
                    f"<= {t.max:g}" if t.max is not None else "",
                ) if s
            ) + f" (weight {t.weight:g})"
            for q, t in problem.targets.items()
        ),
        "- knobs: " + "; ".join(f"{k} {lo:g}-{hi:g}" for k, (lo, hi) in problem.knobs.items()),
        "- fixed: " + ("; ".join(f"{k} = {v:g}" for k, v in problem.fixed.items()) or "none"),
        f"- robot: {robot.name} ({robot.temperature_C[0]:g}-{robot.temperature_C[1]:g} C, "
        f"{robot.volume_ml[0]:g}-{robot.volume_ml[1]:g} mL per dispense)",
        "",
    ]

    lines += ["## Known recipes", "", *recipes_table(family), ""]

    lines += [
        "## Calibration", "",
        f"- status: **{cal.status}** on {cal.n} family recipe(s)"
        + (f" ({', '.join(cal.recipe_ids)})" if cal.recipe_ids else ""),
        f"- parameters: {json.dumps(cal.params)}",
        f"- median relative deviation on the family: "
        f"{'-' if cal.spread is None else f'{cal.spread:.1%}'}",
        f"- band factor: x{cal.band_factor:.2f}",
    ]
    lines += [f"- {note}" for note in cal.notes] + [""]

    lines += ["## Candidates", "", *candidates_table(problem, candidates), ""]

    lines += ["## Novelty", ""]
    for p in proposals:
        n = p.novelty
        lines.append(
            f"- {p.proposal_id}: {'novel' if n.novel else 'NOT novel'}; nearest "
            f"{n.nearest_recipe_id or '(none)'} at distance "
            f"{'-' if n.distance is None else f'{n.distance:.2f}'} (coverage: {n.coverage})"
        )
    lines.append("")

    lines += ["## Proposals", ""]
    for p in proposals:
        lines += proposal_section(p)
    lines += ["## Assumptions", ""] + [f"- {a}" for a in assumptions] + [""]
    return "\n".join(lines)


def recipes_table(family: list[Recipe]) -> list[str]:
    header = "| recipe | method | ratio | T (C) | conc (mM) | main outcome | source |"
    rows = ["|---|---|---|---|---|---|---|"]
    for r in family:
        outcome = next(iter(r.outcomes), None)
        main = f"{outcome.quantity} {outcome.value:g} {outcome.unit}" if outcome else "-"
        src = r.source + (f" ({r.paper_title})" if r.paper_title else "")
        rows.append(
            f"| {r.recipe_id} | {r.method or '-'} "
            f"| {r.conditions.get('ratio_reductant_precursor', '-')} "
            f"| {r.conditions.get('temperature_C', '-')} "
            f"| {r.conditions.get('conc_precursor_mM', '-')} | {main} | {src} |"
        )
    return [header] + rows


def candidates_table(problem: Problem, candidates: list) -> list[str]:
    knob_names = list(problem.knobs)
    header = "| # | score | " + " | ".join(knob_names) + " | predicted | validated |"
    rows = ["|" + "---|" * (len(knob_names) + 4)]
    for i, c in enumerate(candidates, 1):
        pred = "; ".join(
            f"{q} {b.value:.3g} ({b.low:.3g}-{b.high:.3g})" for q, b in c.predicted.items()
        )
        rows.append(
            f"| {i} | {c.score:.3g} | "
            + " | ".join(f"{c.conditions.get(k, '-'):g}" if k in c.conditions else "-"
                         for k in knob_names)
            + f" | {pred} | {'yes' if c.in_validated_region else 'exploratory'} |"
        )
    return [header] + rows


def proposal_section(p) -> list[str]:
    lines = [f"### {p.proposal_id} (score {p.candidate.score:.3g})", ""]
    lines += [f"- conditions: " + "; ".join(
        f"{k} = {v:g}" for k, v in p.candidate.conditions.items())]
    lines += [f"- expected: {p.expected}"]
    lines += ["- steps:"] + [f"  {i}. {s}" for i, s in enumerate(p.steps, 1)]
    lines += ["- measurements:"] + [f"  - {m}" for m in p.measurements]
    lines += ["- controls:"] + [f"  - {c}" for c in p.controls]
    lines += ["- risks:"] + [f"  - {r}" for r in p.risks] + [""]
    return lines


if __name__ == "__main__":
    sys.exit(main())
