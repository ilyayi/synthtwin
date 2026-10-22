"""SynthTwin command line: build cards/vaults, run baselines, score - for the
CO light-off benchmark and for general sweeps.

Usage:

  python -m synthtwin.cli build <gold_dir> <cards_dir> <vault_dir>
  python -m synthtwin.cli baseline <cards_dir> --predictor null|baseline [--model pkg.mod:func] [-o predictions.jsonl]
  python -m synthtwin.cli score <cards_dir> <vault_dir> <predictions.jsonl>
  python -m synthtwin.cli sweep build <gold_dir> <cards_dir> <vault_dir>
  python -m synthtwin.cli sweep baseline <cards_dir> --predictor null|model [--model pkg.mod:fn] [-o predictions.jsonl]
  python -m synthtwin.cli sweep score <cards_dir> <vault_dir> <predictions.jsonl>

score writes scores.jsonl and scores.md (sweep: sweep_scores.jsonl and
sweep_scores.md) next to the predictions file and prints the markdown table.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from synthtwin import sweep
from synthtwin.core.schemas import (
    CaseCard,
    CasePrediction,
    CaseScore,
    SweepCase,
    SweepPrediction,
    SweepScore,
    SweepVault,
)
from synthtwin.lib.baseline import baseline_predict, null_predict
from synthtwin.lib.cards import split_gold
from synthtwin.lib.score import score
from synthtwin.lib.vault import read_sealed, read_vault, write_sealed, write_vault

TABLE_COLUMNS = ["case_id", "predictor", "n_points", "spearman", "t50_mae_K", "band_coverage", "trend_ok"]
SWEEP_TABLE_COLUMNS = ["case_id", "predictor", "quantity", "n_points", "spearman", "mae", "band_coverage", "trend_ok"]


def cmd_build(gold_dir: str, cards_dir: str, vault_dir: str) -> int:
    gold_dir, cards_dir, vault_dir = Path(gold_dir), Path(cards_dir), Path(vault_dir)
    cards_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(gold_dir.glob("*.json")):
        gold = json.loads(f.read_text())
        # keep an existing vault file's canary so rebuilds don't invalidate
        # leak scans of old runs
        vpath = vault_dir / f"{gold['case_id']}.json"
        existing = read_vault(vpath).canary if vpath.exists() else None
        card, entry = split_gold(gold, existing_canary=existing)
        (cards_dir / f"{card.case_id}.json").write_text(card.model_dump_json(indent=2))
        write_vault(vault_dir, entry)
        n += 1
        print(
            f"{card.case_id}: anchor {card.anchor_label} = "
            f"{card.anchor_t50_K:g} K ({len(card.points)} points)"
        )
    print(f"built {n} case(s) into {cards_dir} (vault in {vault_dir})")
    return 0


def load_model(spec: str | None):
    """'package.module:function' -> the light-off model callable (see baseline.py)."""
    if not spec or ":" not in spec:
        raise ImportError("give the light-off model as --model package.module:function")
    module, func = spec.split(":", 1)
    return getattr(importlib.import_module(module), func)


def cmd_baseline(cards_dir: str, predictor: str, out: str, model: str | None = None) -> int:
    cards_dir, out = Path(cards_dir), Path(out)
    run_lightoff = None
    if predictor == "baseline":
        try:
            run_lightoff = load_model(model)
        except (ImportError, AttributeError) as exc:
            print(f"baseline predictor needs a co_lightoff-style model: {exc}", file=sys.stderr)
            return 1
    lines = []
    for f in sorted(cards_dir.glob("*.json")):
        card = CaseCard.model_validate_json(f.read_text())
        pred = null_predict(card) if predictor == "null" else baseline_predict(card, run_lightoff)
        lines.append(pred.model_dump_json())
    out.write_text("".join(line + "\n" for line in lines))
    print(f"wrote {len(lines)} {predictor} prediction(s) to {out}")
    return 0


def cmd_score(cards_dir: str, vault_dir: str, predictions: str) -> int:
    cards_dir, vault_dir, predictions = Path(cards_dir), Path(vault_dir), Path(predictions)
    scores: list[CaseScore] = []
    for line in predictions.read_text().splitlines():
        if not line.strip():
            continue
        pred = CasePrediction.model_validate_json(line)
        card = CaseCard.model_validate_json((cards_dir / f"{pred.case_id}.json").read_text())
        vault = read_vault(vault_dir, pred.case_id)
        scores.append(score(card, vault, pred))
    out = predictions.parent / "scores.jsonl"
    out.write_text("".join(s.model_dump_json() + "\n" for s in scores))
    table = markdown_table(scores)
    (predictions.parent / "scores.md").write_text(table + "\n")
    print(table)
    print(f"wrote {len(scores)} score(s) to {out}")
    return 0


def markdown_table(scores: list[CaseScore]) -> str:
    return _table(TABLE_COLUMNS, [
        [s.case_id, s.predictor, s.n_points,
         "-" if s.spearman is None else f"{s.spearman:.2f}",
         f"{s.t50_mae_K:.1f}", f"{s.band_coverage:.2f}", s.trend_ok]
        for s in scores
    ])


def sweep_markdown_table(scores: list[SweepScore]) -> str:
    return _table(SWEEP_TABLE_COLUMNS, [
        [s.case_id, s.predictor, s.quantity, s.n_points,
         "-" if s.spearman is None else f"{s.spearman:.2f}",
         f"{s.mae:.3g}", f"{s.band_coverage:.2f}", s.trend_ok]
        for s in scores
    ])


def _table(columns: list[str], rows: list[list]) -> str:
    lines = [
        "| " + " | ".join(str(c) for c in columns) + " |",
        "|" + "|".join(["---"] * len(columns)) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


# ------------------------------------------------------------- sweep benchmark
def cmd_sweep_build(gold_dir: str, cards_dir: str, vault_dir: str) -> int:
    gold_dir, cards_dir, vault_dir = Path(gold_dir), Path(cards_dir), Path(vault_dir)
    cards_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(gold_dir.glob("*.json")):
        gold = json.loads(f.read_text())
        # keep an existing vault file's canary so rebuilds don't invalidate
        # leak scans of old runs
        vpath = vault_dir / f"{gold['case_id']}.json"
        existing = read_sealed(vpath, SweepVault).canary if vpath.exists() else None
        card, vault = sweep.split_sweep_gold(gold, existing_canary=existing)
        (cards_dir / f"{card.case_id}.json").write_text(card.model_dump_json(indent=2))
        write_sealed(vault_dir, vault)
        n += 1
        print(
            f"{card.case_id}: anchor {card.anchor_label} ({len(card.points)} points, "
            f"quantities {', '.join(card.quantities)})"
        )
    print(f"built {n} sweep case(s) into {cards_dir} (vault in {vault_dir})")
    return 0


def cmd_sweep_baseline(cards_dir: str, predictor: str, out: str, model: str | None = None) -> int:
    cards_dir, out = Path(cards_dir), Path(out)
    run = None
    if predictor == "model":
        try:
            run = sweep.load_sweep_model(model)
        except (ImportError, AttributeError) as exc:
            print(f"model predictor needs a simulator with predict/calibrate: {exc}", file=sys.stderr)
            return 1
    lines = []
    for f in sorted(cards_dir.glob("*.json")):
        card = SweepCase.model_validate_json(f.read_text())
        pred = sweep.null_predict(card) if predictor == "null" else sweep.model_predict(card, *run)
        lines.append(pred.model_dump_json())
    out.write_text("".join(line + "\n" for line in lines))
    print(f"wrote {len(lines)} {predictor} sweep prediction(s) to {out}")
    return 0


def cmd_sweep_score(cards_dir: str, vault_dir: str, predictions: str) -> int:
    cards_dir, vault_dir, predictions = Path(cards_dir), Path(vault_dir), Path(predictions)
    scores: list[SweepScore] = []
    for line in predictions.read_text().splitlines():
        if not line.strip():
            continue
        pred = SweepPrediction.model_validate_json(line)
        card = SweepCase.model_validate_json((cards_dir / f"{pred.case_id}.json").read_text())
        vault = read_sealed(vault_dir, SweepVault, pred.case_id)
        scores.extend(sweep.score_sweep(card, vault, pred))
    out = predictions.parent / "sweep_scores.jsonl"
    out.write_text("".join(s.model_dump_json() + "\n" for s in scores))
    table = sweep_markdown_table(scores)
    (predictions.parent / "sweep_scores.md").write_text(table + "\n")
    print(table)
    print(f"wrote {len(scores)} score(s) to {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="synthtwin.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_build = sub.add_parser("build", help="split gold cases into cards + vault")
    p_build.add_argument("gold_dir")
    p_build.add_argument("cards_dir")
    p_build.add_argument("vault_dir")
    p_base = sub.add_parser("baseline", help="write null/baseline predictions")
    p_base.add_argument("cards_dir")
    p_base.add_argument("--predictor", choices=["null", "baseline"], required=True)
    p_base.add_argument("-o", "--out", default="predictions.jsonl")
    p_base.add_argument("--model", help="light-off model for --predictor baseline, "
                        "as package.module:function (params dict -> t50_K, t50_K_low, "
                        "t50_K_high, log10_site_scale_used)")
    p_score = sub.add_parser("score", help="score predictions against the vault")
    p_score.add_argument("cards_dir")
    p_score.add_argument("vault_dir")
    p_score.add_argument("predictions")
    p_sweep = sub.add_parser("sweep", help="general sweep benchmark (SweepCase)")
    ssub = p_sweep.add_subparsers(dest="sweep_cmd", required=True)
    s_build = ssub.add_parser("build", help="split gold sweeps into cards + vault")
    s_build.add_argument("gold_dir")
    s_build.add_argument("cards_dir")
    s_build.add_argument("vault_dir")
    s_base = ssub.add_parser("baseline", help="write null/model sweep predictions")
    s_base.add_argument("cards_dir")
    s_base.add_argument("--predictor", choices=["null", "model"], required=True)
    s_base.add_argument("-o", "--out", default="sweep_predictions.jsonl")
    s_base.add_argument("--model", help="simulator for --predictor model, as "
                        "package.module:fn where fn is a class/factory with "
                        ".predict(params) and .calibrate(params, outcomes)")
    s_score = ssub.add_parser("score", help="score sweep predictions against the vault")
    s_score.add_argument("cards_dir")
    s_score.add_argument("vault_dir")
    s_score.add_argument("predictions")
    args = parser.parse_args(argv)
    if args.cmd == "build":
        return cmd_build(args.gold_dir, args.cards_dir, args.vault_dir)
    if args.cmd == "baseline":
        return cmd_baseline(args.cards_dir, args.predictor, args.out, args.model)
    if args.cmd == "score":
        return cmd_score(args.cards_dir, args.vault_dir, args.predictions)
    if args.sweep_cmd == "build":
        return cmd_sweep_build(args.gold_dir, args.cards_dir, args.vault_dir)
    if args.sweep_cmd == "baseline":
        return cmd_sweep_baseline(args.cards_dir, args.predictor, args.out, args.model)
    return cmd_sweep_score(args.cards_dir, args.vault_dir, args.predictions)


if __name__ == "__main__":
    sys.exit(main())
