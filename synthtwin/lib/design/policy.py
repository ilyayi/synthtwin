"""The 60/40 exploit/explore batch policy and the Gaussian process behind it.

pick() is generic (no dataset knowledge): given posterior means mu (lower is
better, matching the repo's score convention) and posterior sds sd, it returns
`batch` indices split ~`1-explore` exploit / ~`explore` explore. Exploit takes
the best mean with a min-distance diversity rule in the unit cube; explore
takes the largest sd among the not-yet-picked (optionally restricted to the
top half by mean -- off by default, see pick).

gp_fit/gp_predict: ARD Matern 5/2 + white noise, inputs min-max scaled to
[0,1], output standardised, hyperparameters by L-BFGS-B on the log marginal
likelihood with restarts. Handles ~1000 training points (one Cholesky per
likelihood evaluation).
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from scipy.spatial.distance import cdist

MIN_DIST = 0.12        # exploit diversity: min unit-cube distance inside a batch
SQRT5 = np.sqrt(5.0)


# ------------------------------------------------------------------ the picker
def pick(
    mu: np.ndarray,
    sd: np.ndarray,
    batch: int,
    explore: float = 0.4,
    chosen: tuple[int, ...] = (),
    x: np.ndarray | None = None,
    min_dist: float = MIN_DIST,
    explore_top_half: bool = False,
) -> tuple[list[int], list[str]]:
    """-> (indices, labels), aligned; "exploit" = best mean, "explore" = largest sd.

    `chosen` are already-committed indices (excluded, but counted for diversity).
    `x` = unit-cube features for the diversity rule; without it the exploit side
    falls back to plain best-mean.
    `explore_top_half` restricts exploration to candidates with mu at or better
    than the median of the free pool: it explores promising regions instead of
    the far corners. Default off: unrestricted sd maximises coverage of the
    unexplored space, which is what the 40 % is for; both are tested.
    """
    mu, sd = np.asarray(mu, float), np.asarray(sd, float)
    taken = list(chosen)
    free = [i for i in range(len(mu)) if i not in set(taken)]
    n_exploit = min(int(round(batch * (1.0 - explore))), len(free))
    indices: list[int] = []

    unit = None
    if x is not None:
        X = np.asarray(x, float)
        span = np.maximum(X.max(0) - X.min(0), 1e-12)
        unit = (X - X.min(0)) / span

    order = sorted(free, key=lambda i: (mu[i], -sd[i]))       # exploit: best mean
    for i in order:
        if len(indices) >= n_exploit:
            break
        if unit is not None and any(np.linalg.norm(unit[i] - unit[j]) < min_dist for j in taken):
            continue
        indices.append(i)
        taken.append(i)

    rest = [i for i in free if i not in set(indices)]         # explore: largest sd
    if explore_top_half and len(rest) > 1:
        med = np.median([mu[i] for i in rest])
        better = [i for i in rest if mu[i] <= med]
        if better:
            rest = better
    for i in sorted(rest, key=lambda i: -sd[i])[: batch - len(indices)]:
        indices.append(i)
    labels = ["exploit"] * n_exploit + ["explore"] * (len(indices) - n_exploit)
    return indices, labels


# ------------------------------------------------------------------ the GP
def _k(ell: np.ndarray, amp: float, A: np.ndarray, B: np.ndarray) -> np.ndarray:
    """Matern 5/2 with ARD lengths `ell`, amplitude `amp`, between rows of A and B."""
    r = cdist(A / ell, B / ell)
    return amp**2 * (1.0 + SQRT5 * r + 5.0 / 3.0 * r**2) * np.exp(-SQRT5 * r)


def gp_fit(
    X: np.ndarray,
    y: np.ndarray,
    restarts: int = 3,
    seed: int = 0,
    noise_floor: float = 1e-3,
    init: np.ndarray | None = None,
    maxiter: int | None = None,
) -> dict:
    """Fit on raw X (n, d), y (n,). -> opaque state for gp_predict.

    `init` warm-starts from a previous fit's `_p` (the benchmark refits every
    round; one short L-BFGS run from the last hyperparameters suffices).
    """
    X, y = np.asarray(X, float), np.asarray(y, float).ravel()
    xmin = X.min(0)
    span = np.maximum(X.max(0) - xmin, 1e-12)
    Xs = (X - xmin) / span
    mu_y, sd_y = float(y.mean()), float(max(y.std(), 1e-12))
    z = (y - mu_y) / sd_y
    d = X.shape[1]
    rng = np.random.default_rng(seed)

    def nll(p: np.ndarray) -> float:
        K = _k(np.exp(p[:d]), float(np.exp(p[d])), Xs, Xs)
        K[np.diag_indices_from(K)] += np.exp(p[d + 1])
        try:
            L = np.linalg.cholesky(K)
        except np.linalg.LinAlgError:
            return 1e6
        a = np.linalg.solve(L.T, np.linalg.solve(L, z))
        return float(0.5 * z @ a + np.log(np.diag(L)).sum() + 0.5 * len(z) * np.log(2 * np.pi))

    best, best_val = None, np.inf
    bounds = [(-7, 7)] * d + [(-4, 4)] + [(np.log(noise_floor), 2)]
    for k in range(max(1, restarts)):
        if k == 0 and init is not None:
            p0 = np.asarray(init, float)
        elif k == 0:
            p0 = np.log(np.r_[np.full(d, 0.5), 1.0, 1e-2])
        else:
            p0 = np.log(np.r_[rng.uniform(0.1, 2.0, d), rng.uniform(0.5, 1.5), rng.uniform(1e-2, 3e-1)])
        r = minimize(nll, p0, method="L-BFGS-B", bounds=bounds, options=None if maxiter is None else {"maxiter": maxiter})
        if r.fun < best_val:
            best, best_val = r.x, float(r.fun)
    ell, amp = np.exp(best[:d]), float(np.exp(best[d]))
    Kt = _k(ell, amp, Xs, Xs)
    Kt[np.diag_indices_from(Kt)] += float(np.exp(best[d + 1]))
    L = np.linalg.cholesky(Kt)
    return {"ell": ell, "amp": amp, "Xs": Xs, "L": L, "alpha": np.linalg.solve(L.T, np.linalg.solve(L, z)),
            "xmin": xmin, "span": span, "mu_y": mu_y, "sd_y": sd_y, "_p": best}


def gp_predict(gp: dict, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """-> (mu, sd) in the original y units. mu is a cost: lower is better."""
    Xs = (np.asarray(X, float) - gp["xmin"]) / gp["span"]
    K = _k(gp["ell"], gp["amp"], Xs, gp["Xs"])                # (n_test, n_train)
    v = np.linalg.solve(gp["L"], K.T)                         # (n_train, n_test)
    mu = gp["mu_y"] + gp["sd_y"] * (K @ gp["alpha"])
    var = np.maximum(gp["amp"] ** 2 - np.einsum("ij,ij->j", v, v), 0.0)
    return mu, gp["sd_y"] * np.sqrt(var)
