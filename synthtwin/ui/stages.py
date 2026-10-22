"""The general pipeline (docs/PIPELINE.md, part A) as data for the UI.

Each stage has the protocol a study must follow there; the study page shows it
next to what this study actually decided at that stage.
"""
from __future__ import annotations

STAGES: list[dict] = [
    {
        "id": "A1", "name": "Problem", "short": "State the target",
        "what": "A problem: material, allowed methods, target outcomes, bounded knobs, fixed conditions.",
        "protocol": [
            "Every target must be measurable on the robot (size, SD/CV, LSPR, DLS).",
            "Every knob uses a canonical conditions key (temperature_C, pH, conc_*_mM, ratio_*, time_min).",
            "An invalid problem stops the run with one message listing every error.",
        ],
    },
    {
        "id": "A2", "name": "Recipe library", "short": "Published recipes",
        "what": "Search published recipes of the same material and method; they calibrate the simulator and set novelty.",
        "protocol": [
            "Every recipe carries its source (DOI or title).",
            "Outcomes are mined only from the same sentence as the value, with units.",
            "A family with fewer than 3 recipes is thin: candidates there are reported as thin, never novel.",
        ],
    },
    {
        "id": "A3", "name": "Gold benchmark", "short": "Past results as tests",
        "what": "One-factor sweeps from open papers, split into cards (one anchor point) and a sealed vault.",
        "protocol": [
            "Two blinded readers extract each series; only values both agree on are kept.",
            "The card reveals one anchor point (median of the sweep); the rest stay in the vault.",
            "Leak scan everything a predictor can see; vault answers are never published or fitted.",
        ],
    },
    {
        "id": "A4", "name": "Simulator", "short": "Model + MD/DFT gate",
        "what": "predict(params) -> bands; calibrate(params, outcomes). Atomistic numbers enter only via physics overrides.",
        "protocol": [
            "Default tier is a continuum model fast enough for an optimiser (< 3 s per prediction).",
            "Use MD/DFT for a parameter only if it is sensitive, poorly constrained by data, and affordable.",
            "Order: literature DFT/experiment, cheap classical MD, new DFT, ML potentials. Record GPU-hours.",
        ],
    },
    {
        "id": "A5", "name": "Validation", "short": "Score vs null",
        "what": "Calibrate on each case's anchor, predict the held-out points, score against the vault.",
        "protocol": [
            "Scores per quantity: Spearman, MAE, band coverage, trend_ok (Spearman >= 0.8 for n >= 4).",
            "Reference: null predictor = anchor value with a +/-30 % band.",
            "A family is validated only with trend_ok and MAE below null; otherwise candidates are exploratory.",
            "Every model change is judged by ablation on the same cases (with/without physics, with/without calibration).",
        ],
    },
    {
        "id": "A6", "name": "Design", "short": "Optimise + novelty",
        "what": "Calibrate on the family, optimise the knobs, drop known recipes, write robot-ready proposals.",
        "protocol": [
            "Latin hypercube, then L-BFGS-B from the best starts; candidates kept apart in knob space.",
            "No family recipes with outcomes: run uncalibrated and widen bands x2.5.",
            "No proposal without a novelty check; proposals stay inside the robot profile.",
        ],
    },
    {
        "id": "A7", "name": "Approval", "short": "A person decides",
        "what": "A person approves every experiment before the robot runs it.",
        "protocol": [
            "The report gives sources, calibration status, validated vs exploratory, nearest known recipe, every assumption.",
            "Nothing runs on the robot without an explicit approval.",
        ],
    },
    {
        "id": "A8", "name": "Robot + feedback", "short": "Run, measure, learn",
        "what": "The robot runs approved proposals; measurements return to the library and the benchmark.",
        "protocol": [
            "Each measurement is compared with the predicted band.",
            "Results return as recipes (A2) and, when they form a sweep, as new held-out cases (A3).",
        ],
    },
]

STAGE_IDS = [s["id"] for s in STAGES]
