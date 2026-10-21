"""SynthTwin: can a simulation predict a published experiment it has not seen?

Gold-case splitting (card + sealed vault), leak scanning, scoring, and the
null / calibrated-model baselines. Used through `python -m synthtwin.cli` and by
harnesses that run predictors on cases.
"""
from synthtwin.baseline import baseline_predict, null_predict
from synthtwin.cards import split_gold
from synthtwin.score import score
from synthtwin.vault import leak_scan, read_vault, write_vault

__all__ = [
    "baseline_predict",
    "leak_scan",
    "null_predict",
    "read_vault",
    "score",
    "split_gold",
    "write_vault",
]
