"""SynthTwin: can a simulation predict a published experiment it has not seen?

Gold-case splitting (card + sealed vault), leak scanning, scoring, and the
null / calibrated-model baselines - for the CO light-off benchmark and for
general sweeps (synthtwin.lib.sweep). Used through `python -m synthtwin.cli` and by
harnesses that run predictors on cases.
"""
from synthtwin.lib.baseline import baseline_predict, null_predict
from synthtwin.lib.cards import split_gold
from synthtwin.lib.score import score
from synthtwin.lib.sweep import score_sweep, split_sweep_gold
from synthtwin.lib.vault import leak_scan, read_vault, write_vault

__all__ = [
    "baseline_predict",
    "leak_scan",
    "null_predict",
    "read_vault",
    "score",
    "score_sweep",
    "split_gold",
    "split_sweep_gold",
    "write_vault",
]
