"""SynthTwin command line: build cards/vaults, run baselines, score.

Usage:

  python -m synthtwin.cli build <gold_dir> <cards_dir> <vault_dir>
  python -m synthtwin.cli baseline <cards_dir> --predictor null|baseline [--model pkg.mod:func] [-o predictions.jsonl]
  python -m synthtwin.cli score <cards_dir> <vault_dir> <predictions.jsonl>

score writes scores.jsonl and scores.md next to the predictions file and
prints the markdown table.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from synthtwin.schemas import CaseCard, CasePrediction, CaseScore
from synthtwin.baseline import baseline_predict, null_predict
from synthtwin.cards import split_gold
from synthtwin.score import score
from synthtwin.vault import read_vault, write_vault

TABLE_COLUMNS = ["case_id", "predictor", "n_points", "spearman", "t50_mae_K", "band_coverage", "trend_ok"]


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
    lines = [
        "| " + " | ".join(TABLE_COLUMNS) + " |",
        "|" + "|".join(["---"] * len(TABLE_COLUMNS)) + "|",
    ]
    for s in scores:
        lines.append(
            "| "
            + " | ".join(
                [
                    s.case_id,
                    s.predictor,
                    str(s.n_points),
                    "-" if s.spearman is None else f"{s.spearman:.2f}",
                    f"{s.t50_mae_K:.1f}",
                    f"{s.band_coverage:.2f}",
                    str(s.trend_ok),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


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
    args = parser.parse_args(argv)
    if args.cmd == "build":
        return cmd_build(args.gold_dir, args.cards_dir, args.vault_dir)
    if args.cmd == "baseline":
        return cmd_baseline(args.cards_dir, args.predictor, args.out, args.model)
    return cmd_score(args.cards_dir, args.vault_dir, args.predictions)


if __name__ == "__main__":
    sys.exit(main())
