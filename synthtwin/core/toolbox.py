"""The tool area: software the builder agents install for themselves.

When installs are allowed, a builder may add any software a method needs
(conda-forge or PyPI packages, source builds) but only inside one folder, the
tool area (default ~/synthtwin-tools):

    envs/<name>      conda environments (created with --override-channels -c conda-forge)
    src/, opt/       source checkouts and their install prefixes
    registry.json    what is installed, how to run it, and a check command that proved it works
    register.py      how a builder adds an entry (the check must pass first)
    .lock            flock'd around every install so concurrent builds do not collide

Every registered tool is listed to later stack designers and builders, so a
code installed for one study is reused by the next.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from synthtwin import protocols

REGISTER = r'''"""Register software installed in this tool area so the platform and later studies can use it.

    python register.py --name NAME --use "what it computes" --run "how to call it" \
        --check "COMMAND THAT PROVES IT WORKS" [--notes "..."] [--version "..."] [--study ID]

The check runs first (from this folder) and must exit 0; the entry replaces any entry of the same name.
"""
import argparse, fcntl, json, subprocess, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
for k in ("name", "use", "run", "check"):
    ap.add_argument("--" + k, required=True)
for k in ("notes", "version", "study"):
    ap.add_argument("--" + k, default="")
a = ap.parse_args()
r = subprocess.run(a.check, shell=True, cwd=HERE, capture_output=True, text=True, timeout=600)
if r.returncode:
    sys.exit(f"check failed (exit {r.returncode}): {(r.stdout + r.stderr)[-800:]}")
with open(HERE / ".lock", "w") as lk:
    fcntl.flock(lk, fcntl.LOCK_EX)
    f = HERE / "registry.json"
    reg = json.loads(f.read_text()) if f.exists() else []
    reg = [t for t in reg if t["name"] != a.name]
    reg.append({"name": a.name, "use": a.use, "run": a.run, "notes": a.notes, "version": a.version,
                "check": a.check, "study": a.study, "date": time.strftime("%Y-%m-%d")})
    f.write_text(json.dumps(reg, indent=1))
print(f"registered {a.name}")
'''

# the install policy lives in synthtwin/protocols/onboard-tool.md (the onboard-tool protocol)
POLICY = protocols.prompt("toolbox.policy")


def ensure(prefix: Path) -> Path:
    prefix = Path(prefix).expanduser()
    for d in ("envs", "src", "opt", "logs"):
        (prefix / d).mkdir(parents=True, exist_ok=True)
    (prefix / "register.py").write_text(REGISTER)
    return prefix


def registry(prefix: Path | None) -> list[dict]:
    f = Path(prefix).expanduser() / "registry.json" if prefix else None
    if not f or not f.is_file():
        return []
    try:
        return json.loads(f.read_text())
    except json.JSONDecodeError:
        return []


def text(prefix: Path | None) -> str:
    """Installed tools, one entry each, for the stack designer and the builder."""
    return "\n".join(f"- {t['name']} {t.get('version', '')} (tool area): {t['use']}\n  run: {t['run']}"
                     + (f"\n  notes: {t['notes']}" if t.get("notes") else "") for t in registry(prefix))


def policy(prefix: Path | None, study: str, conda: str = "~/miniconda3/bin/conda") -> str:
    if not prefix:
        return "- Do not install packages."
    return POLICY.format(prefix=Path(prefix).expanduser(), conda=conda, study=study)


def tools_text(path: Path | None, toolbox: Path | None = None) -> str:
    """The tools a builder or stack designer may use: this python, the tool area's
    registry, and tools.yaml."""
    base = [f"- python: {sys.executable} (numpy, scipy, pyyaml; no scikit-learn); run long jobs with `nice -n 10`"]
    if registry(toolbox):
        base.append(text(toolbox))
    if path and Path(path).is_file():
        cfg = yaml.safe_load(Path(path).read_text()) or {}
        for t in cfg.get("tools", []):
            base.append(f"- {t['name']}: {t.get('use', '')}\n  run: {t.get('run', '')}\n  notes: {t.get('notes', '')}")
        for r in cfg.get("rules", []):
            base.append(f"- RULE: {r}")
    if toolbox:
        base.append(f"- anything else: may be installed into the tool area {toolbox} (conda-forge, PyPI, source builds)")
    return "\n".join(base)