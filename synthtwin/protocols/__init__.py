"""The protocol registry: the workflow as explicit, versioned protocols.

Each protocol is one Markdown file starting with a fenced ```json metadata
block (id, name, version, phases, purpose, inputs, outputs, steps, rules,
tools, prompts) followed by human-readable `## section` prose. Cross-cutting
protocols live in `synthtwin/protocols/<id>.md` (onboard-data, onboard-tool,
visualize); a protocol that belongs to one pipeline step lives in that step's
folder, `synthtwin/steps/<step>/protocol.md`, and is discovered here. Section
headings are one lowercase snake_case word (`## details`, `## brief`, ...);
prompt sections hold text that is EXACTLY what the LLM receives, with runtime
placeholders ({robot}, {budget}, {install}, {condition_keys}, ...) kept as
they are. The engine, the builder, the literature scout and the tool policy
all read their prompts from here, so a study can record which protocol
versions it ran under.

    python -m synthtwin.protocols          list the protocols
    python -m synthtwin.protocols --check  validate the registry

Sections parse by a simple rule: a heading is a line `## name` where name is
lowercase snake_case; the section text runs until the next such heading, with
the heading's line terminator and one separating newline stripped, so prompt
text round-trips byte for byte.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).parent
STEPS = HERE.parent / "steps"

# the study phases of the pipeline: the steps' own order (synthtwin.steps.ORDER)
def _study_phases() -> tuple[str, ...]:
    from synthtwin import steps as steps_mod
    return tuple(steps_mod.ORDER)


STUDY_PHASES = _study_phases()
# every prompt key the engine asks for: COMMON plus each engine.PHASE_SYSTEM key
ENGINE_KEYS = ("common", "goal", "prior", "stack", "stack_other", "sample", "bench", "case",
               "recipe", "robot")

_HEAD = re.compile(r"(?m)^## ([a-z][a-z0-9_]*)$")


class Protocol:
    """One protocol file: its metadata plus the parsed `## sections`."""

    def __init__(self, meta: dict, sections: dict[str, str], path: Path):
        self.id = str(meta.get("id", ""))
        self.name = str(meta.get("name", ""))
        self.version = str(meta.get("version", ""))
        self.phases: list[str] = list(meta.get("phases") or [])
        self.purpose = str(meta.get("purpose", ""))
        self.inputs: list[dict] = list(meta.get("inputs") or [])
        self.outputs: list[dict] = list(meta.get("outputs") or [])
        self.steps: list[dict] = list(meta.get("steps") or [])
        self.rules: list[str] = list(meta.get("rules") or [])
        self.tools: list[str] = list(meta.get("tools") or [])
        self.prompts: dict[str, str] = dict(meta.get("prompts") or {})
        self.sections = sections
        self.path = path

    def meta(self) -> dict:
        """The metadata alone (no prompt bodies), e.g. for the API/UI."""
        return {"id": self.id, "name": self.name, "version": self.version, "phases": self.phases,
                "purpose": self.purpose, "inputs": self.inputs, "outputs": self.outputs,
                "steps": self.steps, "rules": self.rules, "tools": self.tools, "prompts": self.prompts}

    def __repr__(self) -> str:
        return f"<Protocol {self.id} {self.version}>"


def _parse(path: Path) -> Protocol:
    text = path.read_text()
    if not text.startswith("```json\n"):
        raise ValueError(f"{path.name}: does not start with a ```json metadata block")
    end = text.find("\n```", 7)
    if end < 0:
        raise ValueError(f"{path.name}: the metadata block is not closed")
    try:
        meta = json.loads(text[7:end])
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name}: bad metadata JSON: {exc}") from exc
    heads = list(_HEAD.finditer(text))
    sections: dict[str, str] = {}
    for i, m in enumerate(heads):
        body = text[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        sections[m.group(1)] = body[1:] if body.startswith("\n") else body           # heading terminator
        if sections[m.group(1)].endswith("\n"):
            sections[m.group(1)] = sections[m.group(1)][: -1]                        # section separator
    return Protocol(meta, sections, path)


_CACHE: dict[str, Protocol] | None = None


def load_all() -> dict[str, Protocol]:
    """Every protocol, keyed by id (parsed once per process).

    Cross-cutting protocols come from synthtwin/protocols/*.md; per-step ones
    from each step folder's protocol.md (synthtwin/steps/<step>/)."""
    global _CACHE
    if _CACHE is None:
        _CACHE = {}
        files = sorted(HERE.glob("*.md")) + sorted(STEPS.glob("*/protocol.md"))
        for f in files:
            p = _parse(f)
            if p.id in _CACHE:
                raise ValueError(f"{f}: duplicate protocol id {p.id!r}")
            if f.parent == HERE and p.id != f.stem:   # in the registry, the file is named after its id
                raise ValueError(f"{f.name}: declares id {p.id!r}, expected {f.stem!r}")
            _CACHE[p.id] = p
    return _CACHE


def get(pid: str) -> Protocol:
    try:
        return load_all()[pid]
    except KeyError:
        raise ValueError(f"no protocol {pid!r} (have: {', '.join(sorted(load_all()))})") from None


def for_phase(phase: str) -> list[Protocol]:
    """The protocols that run in an engine phase ([] for the off-phase ones)."""
    return [p for p in load_all().values() if phase in p.phases]


def prompt(key: str) -> str:
    """The exact prompt text for an engine key, e.g. "goal", "stack_other", "builder.brief"."""
    for p in load_all().values():
        sec = p.prompts.get(key)
        if sec is not None:
            return p.sections[sec]
    raise ValueError(f"no protocol provides the prompt {key!r} (protocols: "
                     f"{', '.join(sorted(load_all()))})")


def versions() -> dict[str, str]:
    """{protocol id: version}, recorded on every new study."""
    return {pid: p.version for pid, p in load_all().items()}


def manifest() -> list[dict]:
    """The metadata of every protocol, for the API/UI."""
    return [p.meta() for _, p in sorted(load_all().items())]


def validate() -> None:
    """Check the registry is self-consistent; raise ValueError naming the problem."""
    from synthtwin import steps as steps_mod

    all_ = load_all()
    if not all_:
        raise ValueError(f"no protocols found in {HERE}")
    owners: dict[str, str] = {}
    for p in all_.values():
        if not p.version:
            raise ValueError(f"protocol {p.id}: no version")
        for i, s in enumerate(p.steps):
            if not (isinstance(s, dict) and s.get("id")):
                raise ValueError(f"protocol {p.id}: step {i} has no id")
        for ph in p.phases:
            if ph not in STUDY_PHASES:
                raise ValueError(f"protocol {p.id}: unknown phase {ph!r} (known: {', '.join(STUDY_PHASES)})")
        # a protocol file lives in the registry or in one of its own steps' folders
        where = p.path.parent
        if where != HERE and where.name not in p.phases:
            raise ValueError(f"protocol {p.id}: file lives in {where}, not in the registry or one of its "
                             f"phases ({', '.join(p.phases)})")
        for key, sec in p.prompts.items():
            if sec not in p.sections:
                raise ValueError(f"protocol {p.id}: prompt key {key!r} points at missing section {sec!r}")
            if key in owners:
                raise ValueError(f"prompt key {key!r} is declared by both {owners[key]} and {p.id}")
            owners[key] = p.id
    for key in ENGINE_KEYS:
        if key not in owners:
            raise ValueError(f"no protocol provides the engine prompt {key!r}")
    # each step's step.json protocol list matches what the registry says runs there
    for st in steps_mod.STEPS:
        there = sorted(p.id for p in all_.values() if st["id"] in p.phases)
        if sorted(st.get("protocols", [])) != there:
            raise ValueError(f"step {st['id']}: step.json lists {st.get('protocols', [])} but the registry "
                             f"runs {there} there")
    for ph in STUDY_PHASES:
        if not for_phase(ph):
            raise ValueError(f"no protocol covers the engine phase {ph!r}")


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m synthtwin.protocols",
                                 description="list the protocol registry")
    ap.add_argument("--check", action="store_true", help="validate the registry instead of listing")
    a = ap.parse_args(argv)
    if a.check:
        validate()
        print(f"ok: {len(load_all())} protocols")
        return 0
    for pid, p in sorted(load_all().items()):
        print(f"{pid} v{p.version}  phases={','.join(p.phases) or '-'}  steps={len(p.steps)}  {p.purpose}")
    return 0
