"""Score a CasePrediction against the vault: the scoreboard numbers.

Called by the synthtwin CLI (score) and evaluation harnesses. Spearman rank agreement
is computed over ALL points including the anchor; T50 MAE and band coverage
over the held-out (non-anchor) points; trend_ok is spearman >= 0.8 for
n >= 4, exact rank order otherwise (CaseScore.trend_ok per common/schemas).
"""
from __future__ import annotations

from synthtwin.core.schemas import CaseCard, CasePrediction, CaseScore, VaultEntry
from scipy.stats import rankdata, spearmanr


def score(card: CaseCard, vault: VaultEntry, pred: CasePrediction) -> CaseScore:
    measured = {p.label: p.t50_K for p in vault.points}
    predicted = {p.label: p.t50_K for p in pred.points}
    bands = {p.label: (p.low_K, p.high_K) for p in pred.points}
    labels = [p.label for p in card.points if p.label in measured and p.label in predicted]
    m = [measured[l] for l in labels]
    q = [predicted[l] for l in labels]

    spearman: float | None = None
    if len(labels) >= 3 and len(set(m)) > 1 and len(set(q)) > 1:
        r = spearmanr(m, q).statistic
        if r == r:  # NaN guard
            spearman = float(r)

    # a point the predictor skipped counts as a miss, never as silently absent
    expected = [p.label for p in card.points if p.label in measured]
    complete = len(labels) == len(expected)
    held_out = [l for l in labels if l != card.anchor_label]
    n_held_out = sum(1 for l in expected if l != card.anchor_label)
    if held_out:
        t50_mae_K = sum(abs(predicted[l] - measured[l]) for l in held_out) / len(held_out)
        inside = sum(1 for l in held_out if bands[l][0] <= measured[l] <= bands[l][1])
        band_coverage = inside / n_held_out
    else:
        t50_mae_K = 0.0
        band_coverage = 0.0

    if not complete:
        trend_ok = False
    elif len(labels) >= 4:
        trend_ok = spearman is not None and spearman >= 0.8
    else:
        trend_ok = list(rankdata(m)) == list(rankdata(q))

    return CaseScore(
        case_id=card.case_id,
        predictor=pred.predictor,
        n_points=max(len(card.points) - 1, 0),
        spearman=spearman,
        t50_mae_K=t50_mae_K,
        band_coverage=band_coverage,
        trend_ok=trend_ok,
    )
