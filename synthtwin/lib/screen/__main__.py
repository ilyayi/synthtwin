"""CLI: build the index from the LeMat-Synth parquet files, scan it for studies."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from synthtwin.lib.screen import index as ix
from synthtwin.lib.screen import scan as sc


def _index(args) -> int:
    with open(args.out, "w", encoding="utf-8") as fh:
        n = 0
        for row in ix.build(args.parquet):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    size = Path(args.out).stat().st_size
    print(f"{args.out}: {n} rows, {size / 1e6:.0f} MB")
    return 0


def _scan(args) -> int:
    rows = ix.load(args.index)
    query = {"material": args.material, "application": args.application, "metric": args.metric,
             "include": args.include or "", "exclude": args.exclude or "",
             "budget": args.budget, "explore": args.explore}
    r = sc.scan(rows, query)
    m, g = r["metric"], r["global_best"]
    print(" | ".join(f"{lab}: {n}" for lab, n in
                     [(f["label"], f["n"]) for f in r["funnel"]]))
    if g:
        print(f"global best {g['value']:g} {m['unit']} — {g['family']} "
              f"({g['paper']['title'][:60]}, {g['paper'].get('year')})")
    w = max(44, *(len(f["family"]) for f in r["families"][:args.k])) if r["families"] else 44
    print(f"{'#':>2} {'family':<{w}} {'best':>9} {'rep':>4} {'pap':>4} {'score':>6} label")
    for i, f in enumerate(r["families"][:args.k], 1):
        print(f"{i:>2} {f['family']:<{w}} {f['best']['value']:>9.4g} {f['n_reports']:>4} "
              f"{f['n_papers']:>4} {f['score']:>6.3f} {f['label'] or ''}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="synthtwin.lib.screen", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("index", help="build the compact jsonl index from LeMat-Synth parquet files")
    b.add_argument("parquet", nargs="+")
    b.add_argument("--out", required=True)
    s = sub.add_parser("scan", help="scan the index and print the leaderboard")
    s.add_argument("index")
    s.add_argument("--material", required=True)
    s.add_argument("--application", required=True)
    s.add_argument("--metric", help="figure of merit (default: picked from the application)")
    s.add_argument("--include", help="comma-separated words that must appear")
    s.add_argument("--exclude", help="comma-separated words that must not appear")
    s.add_argument("--budget", type=int, default=3, help="how many families to queue")
    s.add_argument("--explore", type=float, default=0.4, help="share of the budget for exploration")
    s.add_argument("--k", type=int, default=15, help="how many families to print")
    args = ap.parse_args(argv)
    try:
        return _index(args) if args.cmd == "index" else _scan(args)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
