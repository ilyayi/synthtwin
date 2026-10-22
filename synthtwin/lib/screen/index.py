"""The compact index over LeMat-Synth: one small JSON row per synthesis.

`build` reads the extracted-synthesis parquet files (pyarrow is the optional
`data` extra and only imported inside it) and yields rows that keep just what
the screener needs: who made what, how, with which conditions and where it was
published — the structured steps stay in the parquet, only their counts travel.
`load` reads such a jsonl file back, caching per path+mtime so the server can
call it on every request.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Iterator

_CACHE: dict[tuple[str, float], list[dict]] = {}


def _year(d: object) -> int | None:
    m = re.match(r"(1[9]\d{2}|20\d{2})", str(d or ""))
    return int(m.group(1)) if m else None


def _row(r: dict, src: str) -> dict:
    ss = r.get("structured_synthesis") or {}
    if not isinstance(ss, dict):
        ss = {}
    steps = [s for s in (ss.get("steps") or []) if isinstance(s, dict)]
    n_cond = sum(1 for s in steps
                 if (s.get("conditions") or {}).get("temperature") is not None
                 or (s.get("conditions") or {}).get("duration") is not None)
    reagents = []
    for m in ss.get("starting_materials") or []:
        name = m.get("name") if isinstance(m, dict) else None
        if name and name.strip():
            reagents.append(name.strip())
    doi, title = r.get("paper_doi") or "", r.get("paper_title") or ""
    material = r.get("synthesized_material") or ""
    return {"id": hashlib.sha1(f"{doi}|{material}|{title}".encode()).hexdigest()[:12],
            "material": material, "category": r.get("material_category") or "",
            "method": r.get("synthesis_method") or "", "title": title,
            "abstract": r.get("paper_abstract") or "", "doi": doi,
            "url": r.get("paper_url") or "", "year": _year(r.get("paper_published_date")),
            "n_steps": len(steps), "n_cond": n_cond, "reagents": reagents[:12], "src": src}


def build(paths) -> Iterator[dict]:
    """Yield one compact row per synthesis from the LeMat-Synth parquet files."""
    import pyarrow.parquet as pq   # the optional `data` extra; not needed to scan

    for p in map(Path, paths):
        src = re.sub(r"[-_].*$", "", p.name) or p.stem   # arxiv-00000-of-... -> arxiv
        for batch in pq.ParquetFile(p).iter_batches(batch_size=512):
            for r in batch.to_pylist():
                yield _row(r, src)


def load(path: str | Path) -> list[dict]:
    """Read an index jsonl, cached per (resolved path, mtime)."""
    p = Path(path)
    key = (str(p.resolve()), p.stat().st_mtime)
    if key not in _CACHE:
        with open(p, encoding="utf-8") as fh:
            _CACHE[key] = [json.loads(line) for line in fh if line.strip()]
    return _CACHE[key]
