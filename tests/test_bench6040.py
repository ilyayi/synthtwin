"""The pool-based benchmark: mechanics on a small synthetic campaign (<5 s)."""
from __future__ import annotations

import numpy as np

from synthtwin.lib.design import bench6040


def toy_pool(n: int = 60) -> dict:
    """Smooth 1-D function: the optimum sits at x=0.5, plus a local trap at x=0.1."""
    rng = np.random.default_rng(7)
    X = np.sort(rng.uniform(0, 1, (n, 1)), axis=0)
    y = np.abs(X[:, 0] - 0.5) + 0.8 * np.exp(-((X[:, 0] - 0.1) ** 2) / 0.01) - 0.7 * np.exp(
        -((X[:, 0] - 0.5) ** 2) / 0.001)
    return {"X": X, "y": y, "features": ["x"], "objective": "toy", "direction": "min",
            "n_raw": n, "n_pool": n}


def test_run_one_random_reaches_something() -> None:
    pool = toy_pool()
    run = bench6040.run_one(pool, None, seed=0, budget=24, batch=6)
    assert run["ns"] == [8, 14, 20, 24]                 # start + capped batches
    assert len(run["best"]) == len(run["ns"])
    assert run["best"][0] >= run["best"][-1]            # best-so-far only improves


def test_run_one_gp_strategy_finds_the_optimum() -> None:
    pool = toy_pool()
    best = float(pool["y"].min())
    run = bench6040.run_one(pool, 0.4, seed=1, budget=40, batch=8)   # the 60/40 mix
    assert min(run["best"]) <= best + 1e-9
    assert run["hit_opt"] is True and run["n_opt"] <= 40


def test_maximise_dataset_reported_in_original_units() -> None:
    pool = toy_pool()
    pool["direction"] = "max"
    pool["y"] = -pool["y"]                              # internal minimise convention
    run = bench6040.run_one(pool, 0.4, seed=2, budget=24, batch=6)
    assert max(run["best"]) == float((-pool["y"]).max())  # reported in the campaign's units
    assert min(run["best"]) == -float(pool["y"].min())


def test_run_dataset_aggregates(tmp_path) -> None:
    import csv
    rows = [[round(float(x), 4), float(y)] for x, y in zip(toy_pool()["X"][:, 0], toy_pool()["y"])]
    with open(tmp_path / "toy.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["x", "toy"])
        w.writerows(rows)
    bench6040.DATASETS["toy"] = ("toy.csv", "toy", "min")
    try:
        out = bench6040.run_dataset("toy", tmp_path / "toy.csv", seeds=3, budget=24,
                                    batch=6, workers=1)
        assert out["n_pool"] == 60 and out["budget"] == 24
        assert set(out["curves"]) == {label for label, _ in bench6040.STRATEGIES}
        for c in out["curves"].values():
            assert len(c["mean"]) == len(c["ns"]) == 4
            assert c["p5"][0] <= c["mean"][0] <= c["p95"][0]
        rnd, mine = out["curves"]["random"], out["curves"]["60/40"]
        assert mine["ef_top1"] == round(rnd["n_top1"] / mine["n_top1"], 3)
    finally:
        del bench6040.DATASETS["toy"]
