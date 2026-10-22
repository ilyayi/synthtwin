"""Pool-based benchmark of the 60/40 exploit/explore policy on literature
optimisation campaigns (Liang et al. 2021, npj Comput Mater 7:188; data
MIT-licensed from PV-Lab/Benchmarking).

The candidate pool is the campaign's measured experiments (replicates of
identical conditions averaged first); an "experiment" returns the literature
measurement; ground truth is the best measured value in the pool. Each run
starts from 8 random points and spends a budget of experiments in batches,
picking each batch with the strategy under test (random, exploit/explore mixes
via policy.pick, GP-EI, GP-LCB kappa=2).

Usage:

  python -m synthtwin.lib.design.bench6040 --data DIR [--datasets ...] \
      --seeds 30 --budget 100 --batch 8 --out results.json
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import multiprocessing as mp
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from synthtwin.lib.design import policy

# name -> (file, objective, direction) ; direction is the ORIGINAL sense
DATASETS: dict[str, tuple[str, str, str]] = {
    "AgNP": ("AgNP.csv", "loss", "min"),                      # Mekki-Berrada et al. 2021
    "AutoAM": ("AutoAM.csv", "Score", "max"),
    "Crossed_barrel": ("Crossed_barrel.csv", "toughness", "max"),
    "P3HT": ("P3HT.csv", "Conductivity (S/cm)", "max"),
    "Perovskite": ("Perovskite.csv", "Instability index", "min"),
}
# label -> ("pick" mix | "ei" | "lcb" | None for random)
STRATEGIES: list[tuple[str, object]] = [
    ("random", None), ("exploit", 0.0), ("80/20", 0.2), ("60/40", 0.4),
    ("40/60", 0.6), ("explore", 1.0), ("EI", "ei"), ("LCB", "lcb"),
]
N_START = 8           # random points every run starts from (Liang et al. use 2; 8 matches our batch)
EI_XI = 0.01          # EI exploration offset, x the objective's range
LCB_KAPPA = 2.0
REFIT_EVERY = 2       # full fit every N rounds; between, one short warm-started L-BFGS run


def load_pool(path: str | Path, direction: str) -> dict:
    """csv -> pool of unique conditions with averaged replicates (minimise convention)."""
    with open(path, encoding="utf-8-sig") as f:      # Perovskite header carries a BOM
        rows = list(csv.reader(f))
    header, raw = rows[0], [[float(v) for v in r] for r in rows[1:] if r and r[0].strip()]
    grouped: dict[tuple, list[float]] = defaultdict(list)
    for r in raw:
        grouped[tuple(r[:-1])].append(r[-1])
    X = np.array(list(grouped.keys()))
    y = np.array([np.mean(v) for v in grouped.values()])
    if direction == "max":                            # everything internal is minimise
        y = -y
    return {"X": X, "y": y, "features": header[:-1], "objective": header[-1],
            "direction": direction, "n_raw": len(raw), "n_pool": len(y)}


def run_one(
    pool: dict, strategy: object, seed: int, budget: int, batch: int = 8,
) -> dict:
    """One seeded campaign -> best-so-far per batch and first-hit counts (censored)."""
    X, y = pool["X"], pool["y"]
    n = len(y)
    budget = min(budget, n)
    rng = np.random.default_rng(seed)
    start = rng.choice(n, size=min(N_START, n), replace=False)
    obs = list(start)
    # top-k thresholds in minimise convention: k-th best pool value
    ys = np.sort(y)
    top1 = ys[max(1, math.ceil(0.01 * n)) - 1]
    top5 = ys[max(1, math.ceil(0.05 * n)) - 1]
    xi = EI_XI * float(y.max() - y.min())

    ns, best = [], []
    sign = -1.0 if pool["direction"] == "max" else 1.0  # report in the campaign's own units
    n_top1 = n_top5 = n_opt = budget + 1              # censored

    def record() -> None:
        nonlocal n_top1, n_top5, n_opt
        b = float(y[obs].min())
        if n_top1 > budget and b <= top1:
            n_top1 = len(obs)
        if n_top5 > budget and b <= top5:
            n_top5 = len(obs)
        if n_opt > budget and b <= ys[0]:
            n_opt = len(obs)
        ns.append(len(obs))
        best.append(sign * b)

    record()                                          # the random start counts
    gp, round_i = None, 0
    while len(obs) < budget:
        rem = np.array([i for i in range(n) if i not in set(obs)])
        take = min(batch, budget - len(obs), len(rem))
        if strategy is None:                          # random
            pick_i = rng.choice(rem, size=take, replace=False)
        else:
            if gp is None or round_i % REFIT_EVERY == 0:
                gp = policy.gp_fit(X[obs], y[obs], restarts=2, seed=seed,
                                   init=None if gp is None else gp["_p"])
            else:                                     # warm refit: one short run from last params
                gp = policy.gp_fit(X[obs], y[obs], restarts=1, seed=seed,
                                   init=gp["_p"], maxiter=60)
            mu, sd = policy.gp_predict(gp, X[rem])
            if strategy == "ei":
                from scipy.stats import norm
                z = (y[obs].min() - mu - xi) / np.maximum(sd, 1e-12)
                ei = norm.cdf(z) * sd + norm.pdf(z) * sd
                pick_i = rem[np.argsort(-ei)[:take]]
            elif strategy == "lcb":
                pick_i = rem[np.argsort(mu - LCB_KAPPA * sd)[:take]]
            else:                                     # a policy.pick mix
                unit = (X - X.min(0)) / np.maximum(X.max(0) - X.min(0), 1e-12)
                idx, _ = policy.pick(mu, sd, take, explore=float(strategy), x=unit[rem])
                pick_i = rem[np.array(idx)]
        obs.extend(int(i) for i in pick_i)
        record()
        round_i += 1
    return {"ns": ns, "best": best, "n_top1": n_top1, "n_top5": n_top5, "n_opt": n_opt,
            "hit_opt": n_opt <= budget}


def aggregate(runs: list[dict], budget: int) -> dict:
    """Seeds -> curve (mean, 5-95 % band) and summary numbers, original units."""
    ns = runs[0]["ns"]
    b = np.array([r["best"] for r in runs])           # (seeds, batches)
    med = lambda key: float(np.median([r[key] for r in runs]))
    return {"ns": ns,
            "mean": [round(float(v), 6) for v in b.mean(0)],
            "p5": [round(float(v), 6) for v in np.percentile(b, 5, axis=0)],
            "p95": [round(float(v), 6) for v in np.percentile(b, 95, axis=0)],
            "n_top1": med("n_top1"), "n_top5": med("n_top5"), "n_opt": med("n_opt"),
            "hit_rate": float(np.mean([r["hit_opt"] for r in runs])),
            "final_best_mean": round(float(b[:, -1].mean()), 6)}


def _worker(args: tuple) -> tuple:
    """(name, path, seed, budget, batch) -> {strategy: run} for one seed."""
    name, path, seed, budget, batch = args
    pool = load_pool(path, DATASETS[name][2])
    out = {}
    for label, strategy in STRATEGIES:
        out[label] = run_one(pool, strategy, seed, budget, batch)
    return name, seed, out


def run_dataset(
    name: str, path: str | Path, seeds: int, budget: int = 100, batch: int = 8,
    workers: int = 8, seed0: int = 0,
) -> dict:
    """All strategies, `seeds` seeds, one dataset -> the JSON record for it."""
    pool = load_pool(path, DATASETS[name][2])
    runs: dict[str, list[dict]] = defaultdict(list)
    jobs = [(name, str(path), seed0 + s, budget, batch) for s in range(seeds)]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=min(workers, 8),
                                 mp_context=mp.get_context("fork")) as ex:
            results = list(ex.map(_worker, jobs))
    else:
        results = [_worker(j) for j in jobs]
    for _, _, per_seed in results:
        for label, run in per_seed.items():
            runs[label].append(run)
    eff_budget = min(budget, pool["n_pool"])
    curves = {label: aggregate(rs, eff_budget) for label, rs in runs.items()}
    rnd = curves["random"]
    for label, c in curves.items():                   # EF vs random (censored runs -> 1.0)
        for k in ("top1", "top5"):
            a, b_ = rnd[f"n_{k}"], c[f"n_{k}"]
            c[f"ef_{k}"] = 1.0 if a > eff_budget and b_ > eff_budget else round(a / b_, 3)
    best0 = float(np.sort(pool["y"])[0])
    return {"objective": pool["objective"], "direction": pool["direction"],
            "features": pool["features"], "n_raw": pool["n_raw"], "n_pool": pool["n_pool"],
            "budget": eff_budget, "best_value": round(best0 if pool["direction"] == "min" else -best0, 6),
            "curves": curves}


def meta(seeds: int, budget: int, batch: int) -> dict:
    return {
        "source": "PV-Lab/Benchmarking (github.com/PV-Lab/Benchmarking), datasets/ dir",
        "licence": "MIT (PV-Lab/Benchmarking; LICENSE file in the data dir)",
        "cite": "Liang et al., 'Benchmarking the performance of Bayesian optimization "
                "across multiple experimental materials science domains', npj Comput Mater 7, 188 (2021); "
                "AgNP campaign: Mekki-Berrada et al., npj Comput Mater 7, 118 (2021)",
        "setup": {"seeds": seeds, "budget": budget, "batch": batch, "n_start": N_START,
                  "pool": "measured experiments, replicates averaged; ground truth = best measured value",
                  "gp": "ARD Matern 5/2 + white noise (policy.gp_fit); full refit every "
                        f"{REFIT_EVERY} rounds, one warm-started L-BFGS run between",
                  "ef": "median experiments of random / of strategy to reach the same top-k% "
                        "(runs that never reach it count as budget+1)"}
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bench6040")
    p.add_argument("--data", required=True, help="dir with the campaign csvs (scripts/fetch_bench_data.sh)")
    p.add_argument("--datasets", nargs="*", default=list(DATASETS), choices=list(DATASETS))
    p.add_argument("--seeds", type=int, default=30)
    p.add_argument("--budget", type=int, default=100)
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--out", default="results.json")
    args = p.parse_args(argv)

    t0 = time.time()
    out = {"meta": meta(args.seeds, args.budget, args.batch), "datasets": {}}
    for name in args.datasets:
        t1 = time.time()
        out["datasets"][name] = run_dataset(
            name, Path(args.data) / DATASETS[name][0], args.seeds, args.budget,
            args.batch, args.workers)
        print(f"{name}: pool {out['datasets'][name]['n_pool']} "
              f"({time.time() - t1:.0f}s)", file=sys.stderr)
    if "AgNP" in out["datasets"]:                     # the headline campaign context
        a = out["datasets"]["AgNP"]
        c = a["curves"]["60/40"]
        out["headline"] = {
            "dataset": "AgNP", "objective": a["objective"], "best_value": a["best_value"],
            "rows": a["n_raw"], "pool": a["n_pool"], "budget": a["budget"],
            "median_n_6040_to_best": c["n_opt"], "hit_rate_6040": c["hit_rate"],
            "note": "the flow-synthesis campaign measured 3295 runs; the 60/40 policy "
                    "reaches its best measured loss in a median of "
                    f"{c['n_opt'] if c['n_opt'] <= a['budget'] else 'more than ' + str(a['budget'])} "
                    f"pool experiments (pool: {a['n_pool']} unique conditions)",
        }
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n")
    print(f"{time.time() - t0:.0f}s -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
