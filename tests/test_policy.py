"""policy.pick splits and gp_fit/gp_predict round-trips."""
from __future__ import annotations

import numpy as np
import pytest

from synthtwin.lib.design.policy import gp_fit, gp_predict, pick


def test_mix_counts_and_labels() -> None:
    mu = np.array([0.1, 5.0, 1.0, 4.0, 0.2, 3.0, 2.0, 6.0])
    sd = np.full(8, 0.5)
    idx, labels = pick(mu, sd, 5, explore=0.4)
    assert len(idx) == 5 and len(set(idx)) == 5
    assert labels.count("exploit") == 3 and labels.count("explore") == 2


def test_exploit_takes_best_mean_explore_takes_widest() -> None:
    mu = np.array([0.0, 1.0, 2.0, 3.0])
    sd = np.array([0.1, 9.0, 0.2, 8.0])
    idx, labels = pick(mu, sd, 4, explore=0.5)          # 2 exploit, 2 explore
    assert idx[:2] == [0, 1]                            # the two best means first
    assert idx[2] == 3                                  # widest sd among the rest
    assert labels == ["exploit", "exploit", "explore", "explore"]


def test_pure_exploit_and_pure_explore() -> None:
    mu = np.array([0.0, 1.0, 2.0, 3.0])
    sd = np.array([0.0, 1.0, 2.0, 3.0])                 # widest sd on the worst mean
    idx, labels = pick(mu, sd, 3, explore=0.0)
    assert idx == [0, 1, 2] and all(l == "exploit" for l in labels)
    idx, labels = pick(mu, sd, 3, explore=1.0)
    assert idx == [3, 2, 1] and all(l == "explore" for l in labels)


def test_exploit_diversity_rule_with_features() -> None:
    # same best mean, but clustered: the diversity rule must spread the picks
    mu = np.array([0.0, 0.01, 0.02, 0.03, 1.0, 1.01])
    sd = np.zeros(6)
    x = np.array([[0.0, 0.0], [0.01, 0.0], [0.02, 0.0], [0.5, 0.5], [0.9, 0.9], [0.91, 0.9]])
    idx, _ = pick(mu, sd, 3, explore=0.0, x=x, min_dist=0.4)
    unit = x / 1.0
    for i in idx:
        for j in idx:
            if i != j:
                assert np.linalg.norm(unit[i] - unit[j]) >= 0.4


def test_chosen_excluded_but_counted() -> None:
    mu = np.zeros(6)
    sd = np.arange(6.0)
    idx, _ = pick(mu, sd, 3, explore=0.0, chosen=(0,))
    assert 0 not in idx and len(idx) == 3


def test_explore_top_half_restricts_by_mean() -> None:
    mu = np.array([0.0, 0.1, 10.0, 11.0])
    sd = np.array([0.1, 8.0, 9.0, 0.2])                 # widest sd is on a bad mean
    _, labels = pick(mu, sd, 2, explore=1.0, explore_top_half=False)
    idx_off, _ = pick(mu, sd, 2, explore=1.0, explore_top_half=False)
    assert set(idx_off) == {2, 1}                       # unrestricted: sd 9 then 8
    idx_on, _ = pick(mu, sd, 2, explore=1.0, explore_top_half=True)
    assert set(idx_on) <= {0, 1}                        # restricted to the better half


def test_gp_recovers_a_smooth_function() -> None:
    rng = np.random.default_rng(0)
    X = rng.uniform(0, 1, (30, 2))
    y = np.sin(6 * X[:, 0]) + 0.5 * X[:, 1] ** 2
    gp = gp_fit(X, y, restarts=2, seed=1)
    Xt = rng.uniform(0.1, 0.9, (100, 2))                # stay in-sample
    mu, sd = gp_predict(gp, Xt)
    assert np.abs(mu - (np.sin(6 * Xt[:, 0]) + 0.5 * Xt[:, 1] ** 2)).mean() < 0.3
    assert (sd >= 0).all() and sd.max() > 0
    # uncertainty grows away from the training data
    _, sd_far = gp_predict(gp, np.array([[5.0, 5.0]]))
    assert sd_far[0] > np.median(sd)


def test_gp_handles_many_points_and_warm_refit() -> None:
    rng = np.random.default_rng(2)
    X = rng.uniform(0, 1, (300, 3))                     # Cholesky path at scale (fits 1000+ fine, just slower)
    y = (X ** 2).sum(1)
    gp = gp_fit(X, y, restarts=1, seed=3)
    mu, _ = gp_predict(gp, X[:20])
    assert np.abs(mu - y[:20]).mean() < 0.05
    gp2 = gp_fit(np.vstack([X, rng.uniform(0, 1, (50, 3))]), np.r_[y, np.zeros(50) + 0.75],
                 restarts=1, seed=3, init=gp["_p"], maxiter=60)   # warm start runs
    assert np.isfinite(gp2["_p"]).all()
