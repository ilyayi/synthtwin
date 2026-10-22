"""synthtwin-recipes command line: build a nanoparticle recipe library, search it.

Usage:

  synthtwin-recipes ingest <parquet...> --out recipes.jsonl
  synthtwin-recipes search problem.yaml recipes.jsonl [-k 20]

ingest prints counts (rows read, nanoparticle recipes, per material, with
size outcomes, with sd, with full conditions) and writes one Recipe per jsonl
line. search prints the ranked hits with a one-line reason each.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from synthtwin.lib.recipes.ingest import lematsynth
from synthtwin.lib.recipes.search import search
from synthtwin.core.schemas import Problem, Recipe


def cmd_ingest(parquets: list[str], out: str) -> int:
    stats: dict = {}
    recipes = lematsynth(parquets, stats)

    per_material: dict[str, int] = {}
    for r in recipes:
        per_material[r.material] = per_material.get(r.material, 0) + 1
    top = sorted(per_material.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    materials = ", ".join(f"{m} {n}" for m, n in top)
    rest = len(per_material) - len(top)
    if rest:
        materials += f", +{rest} more materials"

    def has(quantity: str) -> int:
        return sum(1 for r in recipes if any(o.quantity == quantity for o in r.outcomes))

    def full_conditions(r: Recipe) -> bool:
        return ("temperature_C" in r.conditions and "time_min" in r.conditions
                and any(k.startswith(("ratio_", "conc_")) for k in r.conditions))

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(r.model_dump_json() + "\n" for r in recipes))
    print(f"rows read: {stats['rows_read']}")
    print(f"nanoparticle recipes: {stats['kept']} ({stats['duplicates']} duplicates dropped)")
    print(f"written: {len(recipes)} -> {out_path}")
    print(f"per material: {materials or '-'}")
    print(f"with size outcomes: {has('size_mean_nm')}")
    print(f"with size sd: {has('size_sd_nm')}")
    print(f"with full conditions (T, time, ratio/conc): "
          f"{sum(1 for r in recipes if full_conditions(r))}")
    return 0


def load_library(path: str) -> list[Recipe]:
    return [
        Recipe.model_validate_json(line)
        for line in Path(path).read_text().splitlines()
        if line.strip()
    ]


def cmd_search(problem_path: str, library_path: str, k: int) -> int:
    problem = Problem.model_validate(yaml.safe_load(Path(problem_path).read_text()))
    hits = search(problem, load_library(library_path), k=k)
    print(f"problem {problem.problem_id}: {len(hits)} match(es)")
    for rank, (recipe, score, reason) in enumerate(hits, 1):
        print(f"{rank:3d}  {score:5.2f}  {recipe.recipe_id}  {reason}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="synthtwin-recipes")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_ing = sub.add_parser("ingest", help="LeMat-Synth parquet files -> recipes.jsonl")
    p_ing.add_argument("parquet", nargs="+")
    p_ing.add_argument("--out", required=True, help="output jsonl path")
    p_ser = sub.add_parser("search", help="rank library recipes for a problem")
    p_ser.add_argument("problem", help="problem yaml")
    p_ser.add_argument("library", help="recipes.jsonl from ingest")
    p_ser.add_argument("-k", type=int, default=20, help="hits to print (default 20)")
    args = parser.parse_args(argv)
    if args.cmd == "ingest":
        return cmd_ingest(args.parquet, args.out)
    return cmd_search(args.problem, args.library, args.k)


if __name__ == "__main__":
    sys.exit(main())
