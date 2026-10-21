"""Vault storage for held-out SynthTwin measurements, and leak scanning.

The vault is written by the CLI (build), read by the scorer, and should be scanned
by the harness after every predictor run: the canary and the held-out T50 values must
never appear in anything the agent could see.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from synthtwin.schemas import VaultEntry

LEAK_VALUE_THRESHOLD = 3  # files holding this many held-out values are leaks


def write_vault(vault_dir: Path, entry: VaultEntry) -> Path:
    """Write vault_dir/<case_id>.json with dir mode 700, file mode 600."""
    vault_dir = Path(vault_dir)
    vault_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(vault_dir, 0o700)  # tighten a dir that already existed
    path = vault_dir / f"{entry.case_id}.json"
    # create with 600 from the start so the file is never world-readable
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(entry.model_dump_json(indent=2))
    os.chmod(path, 0o600)
    return path


def read_vault(a: Path, case_id: str | None = None) -> VaultEntry:
    """Read a vault entry. Pass (dir, case_id) or the file path directly."""
    path = Path(a) if case_id is None else Path(a) / f"{case_id}.json"
    return VaultEntry.model_validate_json(path.read_text())


def leak_scan(paths: list[Path], canary: str, values: list[float]) -> list[str]:
    """Report files that leak vault data: the canary, or >= 3 held-out T50
    values (each written to 1 decimal or as an integer, in K or degC).
    Returns one report string per offending file; empty means clean."""
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
            shown = ", ".join(f"{v:g} K" for v in found)
            hits.append(
                f"contains {len(found)} held-out T50 values ({shown})"
            )
        if hits:
            reports.append(f"{p}: " + "; ".join(hits))
    return reports


def _number_pattern(form: str, integer: bool) -> re.Pattern:
    # not preceded by a digit or '.', not followed by a digit (or by a decimal
    # part, for integers, so '448' does not match inside '448.3' but does
    # match at the end of a sentence: '448.')
    tail = r"(?!\d|\.\d)" if integer else r"(?!\d)"
    return re.compile(rf"(?<![\d.]){re.escape(form)}{tail}")


def _value_in(text: str, value_K: float) -> bool:
    """True if value_K appears in K or degC, to 1 decimal or as an integer."""
    forms: list[tuple[str, bool]] = []
    for v in (value_K, value_K - 273.15):
        forms.append((f"{v:.1f}", False))
        forms.append((str(int(round(v))), True))
    return any(_number_pattern(f, i).search(text) for f, i in forms)
