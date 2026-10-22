"""General sweep benchmark: split a gold JSON into a SweepCase card and a
sealed SweepVault, scan for leaks, score SweepPredictions per quantity, and
run the null / calibrated-model baselines.

Called by the CLI (`python -m synthtwin.cli sweep ...`) and by tests. The gold
file has the SweepCase fields (without anchor_*) plus `measured: {label:
[Outcome]}` and `digitised_by`. The anchor is the point whose swept value is
the median (lower median for even n) - deterministic, as in cards.py. The card
reveals only the anchor's outcomes; the vault keeps every measurement plus the
leak-scan canary.
"""
from __future__ import annotations

import importlib
import secrets
from pathlib import Path
from typing import Any, Callable

from scipy.stats import rankdata, spearmanr

from synthtwin.core.schemas import (
    Band,
    CasePoint,
    Outcome,
    SweepCase,
    SweepPrediction,
    SweepScore,
    SweepVault,
)
from synthtwin.lib.vault import LEAK_VALUE_THRESHOLD, _number_pattern

# gold fields that go into the card (everything SweepCase accepts minus the
# anchor fields, which split_sweep_gold derives from the measured outcomes)
CARD_FIELDS = set(SweepCase.model_fields) - {"anchor_label", "anchor_outcomes"}

# simulator contract (docs/PIPELINE.md): predict(params) -> {quantity: Band
# fields}, calibrate(params, outcomes) -> extra params for predict
Predict = Callable[[dict[str, Any]], dict[str, Any]]
Calibrate = Callable[[dict[str, Any], dict[str, float]], dict[str, Any]]


def split_sweep_gold(
    gold: dict, existing_canary: str | None = None
) -> tuple[SweepCase, SweepVault]:
    """Build (card, vault) from a gold dict.

    existing_canary: when rebuilding, pass the canary of the vault file that
    already exists for this case so canaries stay stable across rebuilds.
    """
    measured = {
        label: [Outcome.model_validate(o) for o in outcomes]
        for label, outcomes in gold["measured"].items()
    }
    points = [CasePoint.model_validate(p) for p in gold["points"]]

    # anchor = median swept value (lower median for even n); label breaks ties
    ordered = sorted(points, key=lambda p: (float(p.value), str(p.label)))
    anchor = ordered[(len(ordered) - 1) // 2]
    if anchor.label not in measured:
        raise ValueError(
            f"gold case {gold.get('case_id')!r}: no measured point for "
            f"anchor label {anchor.label!r}"
        )

    card = SweepCase(
        **{k: v for k, v in gold.items() if k in CARD_FIELDS},
        anchor_label=anchor.label,
        anchor_outcomes=measured[anchor.label],
    )
    vault = SweepVault(
        case_id=card.case_id,
        outcomes=measured,
        digitised_by=list(gold["digitised_by"]),
        canary=existing_canary or secrets.token_hex(8),
    )
    return card, vault


def held_out_values(vault: SweepVault, anchor_label: str) -> list[float]:
    """Every measured value of every quantity at the non-anchor points - the
    numbers leak_scan guards (the anchor's outcomes are public)."""
    return [
        o.value
        for label, outcomes in vault.outcomes.items()
        if label != anchor_label
        for o in outcomes
    ]


def leak_scan(paths: list[Path], canary: str, values: list[float]) -> list[str]:
    """Report files that leak vault data: the canary, or >= 3 held-out values
    from any quantity (each written to 1 decimal or as an integer). Returns
    one report string per offending file; empty means clean."""
    reports: list[str] = []
    for p in paths:
        try:
            text = Path(p).read_text(errors="ignore")
        except OSError:  # missing, a directory, binary unreadable - skip
            continue
        hits: list[str] = []
        if canary and canary in text:
            hits.append("contains the vault canary")
        found = [v for v in values if _value_in(text, v)]
        if len(found) >= LEAK_VALUE_THRESHOLD:
            shown = ", ".join(f"{v:g}" for v in found)
            hits.append(f"contains {len(found)} held-out values ({shown})")
        if hits:
            reports.append(f"{p}: " + "; ".join(hits))
    return reports


def _value_in(text: str, value: float) -> bool:
    """True if value appears to 1 decimal or as an integer. Unlike the CO scan
    there is no unit shift: sweep quantities are nm, pct, ... not K vs degC."""
    forms: list[tuple[str, bool]] = [
        (f"{value:.1f}", False),
        (str(int(round(value))), True),
    ]
    return any(_number_pattern(f, i).search(text) for f, i in forms)


def score_sweep(
    case: SweepCase, vault: SweepVault, pred: SweepPrediction
) -> list[SweepScore]:
    """One SweepScore per quantity in case.quantities. Spearman over all
    points; MAE and band coverage over non-anchor points; a quantity the
    prediction skips anywhere is never trend_ok and its missing points count
    as coverage misses (mirrors score.py for the CO benchmark)."""
    scores: list[SweepScore] = []
    for q in case.quantities:
        measured = {
            label: o.value
            for label, outcomes in vault.outcomes.items()
            for o in outcomes
            if o.quantity == q
        }
        predicted = {
            label: bands[q]
            for label, bands in pred.points.items()
            if q in bands
        }
        labels = [
            p.label for p in case.points if p.label in measured and p.label in predicted
        ]
        m = [measured[l] for l in labels]
        pv = [predicted[l].value for l in labels]

        spearman: float | None = None
        if len(labels) >= 3 and len(set(m)) > 1 and len(set(pv)) > 1:
            r = spearmanr(m, pv).statistic
            if r == r:  # NaN guard
                spearman = float(r)

        # a point the predictor skipped counts as a miss, never as silently absent
        expected = [p.label for p in case.points if p.label in measured]
        complete = len(labels) == len(expected)
        held_out = [l for l in labels if l != case.anchor_label]
        n_held_out = sum(1 for l in expected if l != case.anchor_label)
        if held_out:
            mae = sum(abs(predicted[l].value - measured[l]) for l in held_out) / len(held_out)
            inside = sum(
                1 for l in held_out if predicted[l].low <= measured[l] <= predicted[l].high
            )
            band_coverage = inside / n_held_out
        else:
            mae = 0.0
            band_coverage = 0.0

        if not complete:
            trend_ok = False
        elif len(labels) >= 4:
            trend_ok = spearman is not None and spearman >= 0.8
        else:
            trend_ok = list(rankdata(m)) == list(rankdata(pv))

        scores.append(
            SweepScore(
                case_id=case.case_id,
                predictor=pred.predictor,
                quantity=q,
                n_points=max(len(case.points) - 1, 0),
                spearman=spearman,
                mae=mae,
                band_coverage=band_coverage,
                trend_ok=trend_ok,
            )
        )
    return scores


def null_predict(case: SweepCase) -> SweepPrediction:
    """Every point = the anchor's outcomes, band +-30 % relative - the floor
    any real model must beat."""
    anchor = {o.quantity: o for o in case.anchor_outcomes}
    points: dict[str, dict[str, Band]] = {}
    for p in case.points:
        points[p.label] = {
            q: Band(
                value=o.value,
                low=o.value - 0.3 * abs(o.value),
                high=o.value + 0.3 * abs(o.value),
                unit=o.unit,
            )
            for q, o in anchor.items()
        }
    return SweepPrediction(case_id=case.case_id, predictor="null", points=points)


def model_predict(case: SweepCase, predict: Predict, calibrate: Calibrate) -> SweepPrediction:
    """Calibrate the simulator on the anchor's outcomes, then predict every
    point with conditions = point.conditions plus the calibrated parameters."""
    anchor = next(p for p in case.points if p.label == case.anchor_label)
    outcomes = {o.quantity: o.value for o in case.anchor_outcomes}
    calibrated = calibrate(dict(anchor.conditions), outcomes) or {}
    points: dict[str, dict[str, Band]] = {}
    for p in case.points:
        res = predict({**p.conditions, **calibrated}) or {}
        points[p.label] = {
            q: Band(
                value=float(b["value"]),
                low=float(b["low"]),
                high=float(b["high"]),
                unit=str(b["unit"]),
            )
            for q, b in res.items()
        }
    return SweepPrediction(case_id=case.case_id, predictor="baseline", points=points)


def load_sweep_model(spec: str | None) -> tuple[Predict, Calibrate]:
    """'package.module:fn' -> (predict, calibrate). fn is a class or factory
    returning an object with .predict(params) and .calibrate(params, outcomes)
    (the simulator contract); a non-callable fn is used as the object itself."""
    if not spec or ":" not in spec:
        raise ImportError("give the simulator as --model package.module:function")
    module, func = spec.split(":", 1)
    obj = getattr(importlib.import_module(module), func)
    model = obj() if callable(obj) else obj
    return model.predict, model.calibrate
