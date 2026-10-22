"""The self-improving harness (adapted from Harness2, Xu et al. 2026,
arXiv 2610.14224): the model stays frozen; the harness around each step's
protocol prompt — an overlay of adopted edits plus a lessons library —
improves at test time, without labels, from observed evidence only.

Per step, stored OUTSIDE the repo under the server's data dir:

    <data>/harness/<step>/overlay.md     the current overlay (absent = v0)
                  overlay.vN.md          every adopted version, kept
                  state.json             the current version, when and why
                  EXPERIENCE.md          lessons (append-only) + overlay changes
                  ledger.jsonl           every reflect and evolve run

reflect  after a step is confirmed (or a robot result lands): one structured
         call writes one row per changed component (helped / hurt / no observed
         effect / confounded — prefer confounded on thin evidence) and at most
         one lesson (cue, lesson, evidence, confidence), or none.
evolve   Propose (an editor drafts an invariant and a domain overlay candidate,
         each traced to a moment in a recorded trajectory — a divergence between
         runs beats a repeated concrete failure beats a visible unrealised
         risk — mapped to the cheapest component; KEEP_BASE allowed) ->
         Probe (the step's agent turn is replayed on k recorded studies with
         base / INV / DOM, same prompt rebuilt from the stored study state) ->
         Compose (a composer adopts, merges or keeps base from the behavioural
         contrast of the anonymised outputs, on a six-point checklist; a run
         that does not deliver is unsafe).
inject   appends a short "## Harness for this step" section (overlay + the
         most relevant lessons, by cue match) to the step's system prompt;
         with nothing stored the prompt is byte-identical.

Evidence never includes the vault or held-out gold answers: only the study's
own chat (the user's corrections), the confirm body, the phase record (bench
QA verdicts and scores, robot results vs predicted bands).

    python -m synthtwin.core.harness reflect --data DIR --step stack --study ID
    python -m synthtwin.core.harness evolve  --data DIR --step stack [--k 2]
    python -m synthtwin.core.harness show    --data DIR [--step stack]
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from synthtwin import protocols, steps

MAX_LESSONS = 5        # injected per turn, most relevant first
WORD = re.compile(r"[a-z0-9_]{4,}")
CHECKS = ("delivery", "conformance", "fidelity", "consistency", "fitness", "finish")
VERDICTS = ("helped", "hurt", "no observed effect", "confounded")


# ---------------------------------------------------------------- prompts
REFLECT_SYSTEM = """You are the reflector of SynthTwin's self-improving harness. After one step of one \
study you see what happened: the conversation at that step (the user's corrections are the strongest \
signal), what the researcher confirmed (with their changes), and the step's record (bench QA verdicts, \
benchmark scores, robot results vs the predicted bands). Sealed benchmark answers are never shown.

Write two things, conservatively:
1. rows: one row per harness component that CHANGED and whose effect this step could observe (the \
overlay, a lesson). Verdicts: helped / hurt / no observed effect / confounded. On thin evidence prefer \
confounded. No changed component, or nothing observable: rows = [].
2. at most ONE lesson for later studies at this step, or none (omit it). A lesson is a cue (a \
recognisable situation, a few words a later turn can match on), the lesson itself (one imperative \
sentence the agent can act on), evidence (study id, step, what happened — one line) and confidence. \
Only write a lesson a later study could actually use; trivia and restatements of the protocol get none."""

EDITOR_SYSTEM = """You are the harness editor of SynthTwin. The model is frozen; you improve the \
harness: a short overlay appended to this step's system prompt, plus its lesson library.

Draft TWO candidate overlay edits from the recorded trajectories:
- inv: an INVARIANT edit — how the agent works (what it always does or checks at this step).
- dom: a DOMAIN edit — what a practitioner knows (chemistry, simulation craft, robot practice).

Each candidate must trace to a specific moment in a trajectory (strongest first: a divergence between \
runs > a repeated concrete failure > a visible unrealised risk), be mapped to the cheapest component \
that fixes it (the overlay text, or a lesson), and be an edit the overlay can carry. KEEP_BASE is \
allowed and honourable when no edit has earned its place.

The overlay is short (under ~120 words), imperative, self-contained lines the agent reads as its own \
instructions. No placeholders, no meta-talk about overlays or harnesses, nothing the protocol already says."""

COMPOSER_SYSTEM = """You are the composer of SynthTwin's harness. You see, per recorded study, the \
anonymised outputs of replaying the step's agent turn under candidate overlays (labels A/B/C, shuffled; \
each label's overlay text is shown). Adopt the better candidate, merge their strengths into one overlay, \
or keep the base — but a run that does not deliver (empty or useless reply, missing structure) is unsafe \
and cannot be adopted.

Check, per candidate, and say so in the reason: delivery (a usable turn came out), conformance (the \
requested shape: the step's schema fields present), fidelity (numbers and claims trace to the study \
state, not invented), internal consistency, operational fitness (would help the next real study at this \
step), finish (no placeholders or dangling references)."""


# ---------------------------------------------------------------- schemas
_CAND = {"type": "object", "properties": {
    "action": {"enum": ["EDIT", "KEEP_BASE"]},
    "overlay": {"type": "string", "description": "the overlay text (empty for KEEP_BASE)"},
    "moment": {"type": "string", "description": "the trajectory moment this traces to"},
    "evidence": {"enum": ["divergence", "repeated failure", "unrealised risk"]},
    "component": {"type": "string", "description": "the cheapest component it maps to"}},
    "required": ["action", "overlay", "moment", "component"]}
PROPOSE_SCHEMA = {"type": "object", "properties": {"inv": _CAND, "dom": _CAND},
                  "required": ["inv", "dom"]}
REFLECT_SCHEMA = {"type": "object", "properties": {
    "rows": {"type": "array", "items": {"type": "object", "properties": {
        "component": {"type": "string"}, "verdict": {"enum": list(VERDICTS)}, "note": {"type": "string"}},
        "required": ["component", "verdict"]}},
    "lesson": {"type": "object", "properties": {
        "cue": {"type": "string"}, "lesson": {"type": "string"}, "evidence": {"type": "string"},
        "confidence": {"enum": ["low", "medium", "high"]},
        "verdict": {"enum": list(VERDICTS)}},
        "required": ["cue", "lesson", "evidence", "confidence"]}},
    "required": ["rows"]}
COMPOSE_SCHEMA = {"type": "object", "properties": {
    "decision": {"enum": ["adopt", "merge", "keep_base"]},
    "choice": {"enum": ["inv", "dom"], "description": "which candidate to adopt (ignored on merge/keep)"},
    "merged_overlay": {"type": "string"},
    "reason": {"type": "string"},
    "checks": {"type": "object", "properties": {c: {"enum": ["ok", "risk", "fail"]} for c in CHECKS},
               "required": list(CHECKS)}},
    "required": ["decision", "reason", "checks"]}


def _role(llm: Any, which: str):
    """llm.role("plan")/("work") when the backend has roles, else the same llm."""
    fn = getattr(llm, "role", None)
    return fn(which) if callable(fn) else llm


# ---------------------------------------------------------------- storage
def _now() -> float:
    return time.time()


class Harness:
    """One data dir's harness state: overlays, lessons, ledger, per step."""

    def __init__(self, data_dir: str | Path):
        self.root = Path(data_dir) / "harness"

    def dir(self, step: str) -> Path:
        steps.get(step)                      # raises for unknown steps
        return self.root / step

    # ------------------------------------------------------------ overlay
    def _state(self, step: str) -> dict:
        f = self.dir(step) / "state.json"
        try:
            return json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            return {"current": 0, "versions": {}}

    def _write_state(self, step: str, st: dict) -> None:
        d = self.dir(step)
        d.mkdir(parents=True, exist_ok=True)
        (d / "state.json").write_text(json.dumps(st, indent=1))

    def overlay(self, step: str) -> str:
        """The current overlay text ('' when none was ever adopted)."""
        if not self._state(step)["current"]:
            return ""
        try:
            return (self.dir(step) / "overlay.md").read_text()
        except OSError:
            return ""

    def version(self, step: str) -> int:
        return int(self._state(step)["current"])

    def history(self, step: str) -> list[dict]:
        st = self._state(step)
        return [{"version": int(v), **meta} for v, meta in sorted(st["versions"].items(), key=lambda kv: int(kv[0]))]

    def save_overlay(self, step: str, text: str, note: str = "") -> int:
        """Version the overlay (v1, v2, ... kept as overlay.vN.md; overlay.md = current)."""
        text = (text or "").strip()
        if not text:
            raise ValueError("an overlay must not be empty")
        st = self._state(step)
        n = max([int(v) for v in st["versions"]] + [0]) + 1
        d = self.dir(step)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"overlay.v{n}.md").write_text(text)
        (d / "overlay.md").write_text(text)
        st.update(current=n, updated=_now())
        st["versions"][str(n)] = {"at": _now(), "note": note[:300]}
        self._write_state(step, st)
        return n

    def rollback(self, step: str, version: int) -> dict:
        """Point the current overlay back at an earlier version (the file is kept)."""
        st = self._state(step)
        if str(version) not in st["versions"]:
            raise ValueError(f"no overlay version {version} for step {step!r} "
                             f"(have: {', '.join(sorted(st['versions'], key=int)) or 'none'})")
        text = (self.dir(step) / f"overlay.v{version}.md").read_text()
        (self.dir(step) / "overlay.md").write_text(text)
        st.update(current=int(version), updated=_now())
        self._write_state(step, st)
        return {"step": step, "version": int(version), "at": _now()}

    # ------------------------------------------------------------ lessons
    def experience(self, step: str) -> list[dict]:
        """Every EXPERIENCE.md block (lessons and overlay changes), in file order."""
        try:
            text = (self.dir(step) / "EXPERIENCE.md").read_text()
        except OSError:
            return []
        rows, cur = [], None
        for line in text.splitlines():
            m = re.match(r"^## (lesson|change) (\S+) (.*)$", line)
            if m:
                cur = {"kind": m.group(1), "id": m.group(2), "at": m.group(3).strip()}
                rows.append(cur)
            elif cur and line.startswith("- "):
                k, _, v = line[2:].partition(": ")
                cur[k] = v.strip()
        return rows

    def lessons(self, step: str) -> list[dict]:
        return [r for r in self.experience(step) if r["kind"] == "lesson"]

    def append_lesson(self, step: str, lesson: dict) -> str:
        """One lesson block, appended (the file is append-only; nothing is edited away)."""
        rows = self.experience(step)
        lid = f"l{sum(1 for r in rows if r['kind'] == 'lesson') + 1}"
        block = [f"## lesson {lid} {time.strftime('%Y-%m-%d %H:%M', time.localtime(_now()))}"]
        for k in ("cue", "lesson", "evidence", "study", "confidence", "verdict"):
            v = " ".join(str(lesson.get(k, "")).split()) or ("confounded" if k == "verdict" else "")
            if v:
                block.append(f"- {k}: {v}")
        d = self.dir(step)
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "EXPERIENCE.md", "a") as fh:
            fh.write("\n".join(block) + "\n\n")
        return lid

    def append_change(self, step: str, change: dict) -> str:
        rows = self.experience(step)
        cid = f"c{sum(1 for r in rows if r['kind'] == 'change') + 1}"
        block = [f"## change {cid} {time.strftime('%Y-%m-%d %H:%M', time.localtime(_now()))}"]
        for k, v in change.items():
            v = " ".join(str(v).split())
            if v:
                block.append(f"- {k}: {v}")
        d = self.dir(step)
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "EXPERIENCE.md", "a") as fh:
            fh.write("\n".join(block) + "\n\n")
        return cid

    # ------------------------------------------------------------ ledger
    def log(self, step: str, row: dict) -> None:
        d = self.dir(step)
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "ledger.jsonl", "a") as fh:
            fh.write(json.dumps(row, default=str) + "\n")

    def ledger(self, step: str) -> list[dict]:
        try:
            return [json.loads(x) for x in (self.dir(step) / "ledger.jsonl").read_text().splitlines() if x.strip()]
        except (OSError, json.JSONDecodeError):
            return []

    # ------------------------------------------------------------ injection
    def inject(self, step: str, system: str, context: dict | None = None, overlay: str | None = None) -> str:
        """The step's system prompt plus its harness (overlay + <= 5 cue-matched lessons).

        With no overlay and no lessons the prompt comes back byte-identical. `overlay`
        overrides the stored text (probe runs contrast candidates without writing)."""
        text = self.overlay(step) if overlay is None else (overlay or "")
        lessons = self.lessons(step)
        if not text and not lessons:
            return system
        out = system + "\n\n## Harness for this step\n"
        if text:
            out += text.strip() + "\n"
        if lessons:
            ctx = json.dumps(context or {}, default=str).lower()
            pick = sorted(lessons, key=lambda l: (-_cue_score(l, ctx), str(l.get("at", ""))))
            out += "\nLessons from earlier studies (cue — lesson):\n" + "\n".join(
                f"- {l.get('cue', '')} — {l.get('lesson', '')}"
                + (f" (evidence: {l['study']})" if l.get("study") else "")
                for l in pick[:MAX_LESSONS]) + "\n"
        return out

    # ------------------------------------------------------------ summaries
    def status(self, step: str) -> dict:
        s = steps.get(step)
        pids = s.get("protocols") or []
        proto = protocols.get(pids[0]) if pids else None
        ev = next((r for r in reversed(self.ledger(step)) if r.get("kind") == "evolve"), None)
        return {"step": step, "name": s["name"], "short": s.get("short", ""), "icon": s.get("icon", "chart"),
                "protocol": proto.id if proto else "", "protocol_version": proto.version if proto else "",
                "overlay_version": self.version(step), "lessons": len(self.lessons(step)),
                "last_evolve": ({"at": ev.get("at"), "decision": ev.get("composer", {}).get("decision"),
                                 "reason": ev.get("composer", {}).get("reason", "")[:300]} if ev else None),
                "updated": self._state(step).get("updated")}

    def detail(self, step: str) -> dict:
        ev = next((r for r in reversed(self.ledger(step)) if r.get("kind") == "evolve"), None)
        vers = {"0": ""}                                  # the base prompt, no overlay
        for v in self.history(step):
            try:
                vers[str(v["version"])] = (self.dir(step) / f"overlay.v{v['version']}.md").read_text()
            except OSError:
                pass
        return self.status(step) | {"overlay": self.overlay(step), "history": self.history(step),
                                    "overlays": vers, "experience": self.experience(step),
                                    "ledger": self.ledger(step)[-25:]}


def _cue_score(lesson: dict, ctx_lower: str) -> int:
    """How well a lesson's cue fits this study's state (token hits; 0 = no context)."""
    toks = set(WORD.findall((str(lesson.get("cue", "")) + " " + str(lesson.get("lesson", ""))).lower()))
    return sum(1 for t in toks if t in ctx_lower) if ctx_lower else 0


# ---------------------------------------------------------------- trajectories
def _prune(obj: Any, strings: int = 400, lists: int = 8) -> Any:
    """Small enough for a prompt: short strings, short lists, structure kept."""
    if isinstance(obj, dict):
        return {k: _prune(v, strings, lists) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_prune(v, strings, lists) for v in obj[:lists]]
    if isinstance(obj, str):
        return obj[:strings]
    return obj


def trajectory(sid: str, step: str, s: dict, body: dict | None = None, trigger: str = "confirm") -> dict:
    """What the reflector sees of one step: the chat at the step (the user's
    corrections), the confirm/result body, and the step's own record. Sealed
    benchmark answers live only in the vault and never reach this."""
    chat = [{"role": m["role"], "text": str(m.get("text", ""))[:700]}
            for m in (s.get("chat") or []) if m.get("phase") == step][-10:]
    P = s.get("phases", {}).get(step) or {}
    rec = json.dumps(_prune({k: v for k, v in P.items() if k != "status"}), default=str)
    return {"study": sid, "step": step, "trigger": trigger, "title": s.get("title", ""),
            "confirm": {k: v for k, v in (body or {}).items() if k != "text"} or None,
            "chat": chat,
            "record": rec[:4000] if len(rec) > 4000 else json.loads(rec)}


# ---------------------------------------------------------------- reflect
def reflect(llm: Any, h: Harness, step: str, traj: dict) -> dict:
    """One structured call after a step: rows per changed component, at most one
    lesson (or none). Everything lands in the ledger; a lesson also in EXPERIENCE.md."""
    prompt = json.dumps({
        "step": step, "overlay_now": h.overlay(step)[:1500],
        "lessons_now": [{"cue": l.get("cue"), "lesson": l.get("lesson")} for l in h.lessons(step)[-8:]],
        "recent_changes": [r for r in h.experience(step) if r["kind"] == "change"][-3:],
        "trajectory": traj}, default=str)
    ans = llm.ask(REFLECT_SYSTEM, prompt, REFLECT_SCHEMA)
    rows = [r for r in (ans.get("rows") or [])
            if isinstance(r, dict) and r.get("component") and r.get("verdict") in VERDICTS]
    row = {"at": _now(), "kind": "reflect", "study": traj.get("study"), "step": step,
           "trigger": traj.get("trigger"), "rows": rows}
    lesson = ans.get("lesson")
    if isinstance(lesson, dict) and str(lesson.get("cue", "")).strip() and str(lesson.get("lesson", "")).strip():
        row["lesson"] = h.append_lesson(step, lesson | {"study": traj.get("study", "")})
    h.log(step, row)
    return row


# ---------------------------------------------------------------- evolve
def reached(step: str, s: dict) -> bool:
    """A recorded study this step's turn can be replayed on (the step happened)."""
    P = (s.get("phases") or {}).get(step)
    return bool(P) and (P.get("status") in ("awaiting_user", "done", "working") or len(P) > 1)


def recent_studies(agent, step: str, n: int = 2) -> list[dict]:
    out = []
    for f in agent.dir.glob("*.json"):
        try:
            s = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if s.get("kind") == "agent" and reached(step, s):
            out.append(s)
    out.sort(key=lambda s: -s.get("created", 0))
    return out[:n]


def _at_step(s: dict, step: str) -> dict:
    """The stored study, read as if it were at `step` (replays rebuild the same prompt)."""
    s = json.loads(json.dumps(s, default=str))
    s["phase"] = step
    return s


def _probe_out(ans: Any) -> dict:
    """One replayed turn, summarised for the composer (full outputs stay in the ledger)."""
    ok = isinstance(ans, dict) and str(ans.get("reply", "")).strip()
    return {"delivered": bool(ok), "ready": bool(isinstance(ans, dict) and ans.get("ready")),
            "reply": str(ans.get("reply", ""))[:700] if isinstance(ans, dict) else "",
            "fields": sorted(k for k in (ans or {}) if not str(k).startswith("_"))[:12] if ok else []}


def _candidate(c: Any) -> dict:
    if not isinstance(c, dict) or c.get("action") != "EDIT" or not str(c.get("overlay", "")).strip():
        return {"action": "KEEP_BASE"}
    return {"action": "EDIT", "overlay": str(c["overlay"]).strip()[:2000],
            "moment": str(c.get("moment", ""))[:400], "evidence": c.get("evidence", ""),
            "component": str(c.get("component", ""))[:120]}


def evolve(agent, llm_plan: Any, llm_work: Any, step: str, studies: list[dict] | None = None,
           k: int = 2, h: Harness | None = None) -> dict:
    """Propose -> Probe -> Compose on one step; versions the overlay and writes
    the ledger + an EXPERIENCE row. LLM calls go through the given backends
    (Stub in tests); roles split plan/work when the backend has them."""
    from synthtwin.core import engine        # SCHEMAS; late: engine imports this module
    h = h or Harness(agent.cfg.data_dir)
    steps.get(step)
    studies = [s for s in (studies if studies is not None else recent_studies(agent, step, k))
               if reached(step, s)][:k]
    if not studies:
        raise ValueError(f"no recorded studies have reached the {step} step to probe on")
    plan, work = _role(llm_plan, "plan"), _role(llm_work, "work")
    trajs = [trajectory(s["id"], step, s) for s in studies]

    # Propose: an invariant and a domain overlay candidate, or KEEP_BASE
    prop = plan.ask(EDITOR_SYSTEM, json.dumps({
        "step": step, "step_purpose": steps.get(step).get("what_happens", ""),
        "overlay_now": h.overlay(step)[:1500],
        "lessons_now": [{"cue": l.get("cue"), "lesson": l.get("lesson")} for l in h.lessons(step)[-8:]],
        "trajectories": trajs}, default=str), PROPOSE_SCHEMA)
    inv, dom = _candidate(prop.get("inv")), _candidate(prop.get("dom"))
    arms = {a: c["overlay"] for a, c in (("base", {"overlay": ""}), ("inv", inv), ("dom", dom))
            if a == "base" or c["action"] == "EDIT"}

    # Probe: replay the step's turn on each study under each arm (same stored prompt)
    probes = []
    if len(arms) > 1:
        for s in studies:
            key, system, prompt, ctx = agent.turn_parts(_at_step(s, step))
            outs = {}
            for arm, ov in arms.items():
                ans = work.ask(h.inject(step, system, ctx, overlay=ov or None), prompt, engine.SCHEMAS[key])
                outs[arm] = _probe_out(ans)
            probes.append({"study": s["id"], "arms": outs})

    # Compose: the anonymised, shuffled contrast; then adopt / merge / keep base
    composer, text = {"decision": "keep_base",
                      "reason": "both candidates were KEEP_BASE: no edit earned a probe"}, ""
    if probes:
        import random
        labels = ["A", "B", "C"][:len(arms)]
        random.shuffle(labels)
        by_label = dict(zip(labels, list(arms)))
        shown = [{"label": lab, "overlay": arms[arm] or "(the base prompt, unchanged)"}
                 for lab, arm in by_label.items()]
        contrast = [{"study": p["study"], "labels": {lab: p["arms"][arm] for lab, arm in by_label.items()}}
                    for p in probes]
        comp = plan.ask(COMPOSER_SYSTEM, json.dumps(
            {"step": step, "candidates": shown, "contrast": contrast,
             "note": "labels are shuffled and carry no meaning; a candidate that does not deliver is unsafe"},
            default=str), COMPOSE_SCHEMA)
        decision, choice = comp.get("decision"), (comp.get("choice") if comp.get("decision") == "adopt" else None)
        if decision == "adopt" and choice in arms and arms[choice]:
            text = arms[choice]
        elif decision == "merge" and str(comp.get("merged_overlay", "")).strip():
            text = str(comp["merged_overlay"]).strip()[:2000]
        else:
            decision = "keep_base"        # an adopt nothing was named, or a merge without text
        composer = {"decision": decision, "choice": choice,
                    "reason": str(comp.get("reason", "")), "checks": comp.get("checks") or {}}

    row = {"at": _now(), "kind": "evolve", "step": step, "k": len(studies), "studies": [s["id"] for s in studies],
           "candidates": {"inv": inv, "dom": dom}, "probes": probes, "composer": composer,
           "overlay_version": h.version(step)}
    if text:
        note = f"{composer['decision']}" + (f" ({composer['choice']})" if composer.get("choice") else "")
        row["overlay_version"] = h.save_overlay(step, text, note=note + ": " + composer["reason"])
        row["overlay"] = text
        h.append_change(step, {"overlay": f"v{row['overlay_version']}", "action": note,
                               "reason": composer["reason"][:400], "evidence": ", ".join(row["studies"])})
    h.log(step, row)
    return row


# ---------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    import argparse
    from synthtwin.core import engine, llm as llmmod

    ap = argparse.ArgumentParser(prog="python -m synthtwin.core.harness",
                                 description="the self-improving harness: reflect, evolve, show")
    common = argparse.ArgumentParser(add_help=False)     # after the subcommand, as documented
    common.add_argument("--data", required=True, help="the server's data dir (studies/ and harness/ inside)")
    common.add_argument("--llm", default="claude", help="backend: claude | stub")
    common.add_argument("--binary", default="claude", help="the headless CLI to run (e.g. glm)")
    common.add_argument("--model", default=None)
    common.add_argument("--library", default=None, help="recipes.jsonl (engine context; default: examples)")
    common.add_argument("--robot", default=None, help="robot.yaml (engine context; default: examples)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("reflect", parents=[common], help="reflect on one recorded study at a step")
    rp.add_argument("--step", required=True)
    rp.add_argument("--study", required=True)
    ep = sub.add_parser("evolve", parents=[common], help="propose-probe-compose a new overlay for a step")
    ep.add_argument("--step", required=True)
    ep.add_argument("--k", type=int, default=2, help="recorded studies to probe on")
    sp = sub.add_parser("show", parents=[common], help="the harness state, per step or one step in detail")
    sp.add_argument("--step", default=None)
    a = ap.parse_args(argv)

    root = Path(__file__).parent.parent.parent
    lib = Path(a.library) if a.library else root / "examples" / "recipes.jsonl"
    robot = Path(a.robot) if a.robot else root / "examples" / "robot.yaml"
    llm = llmmod.Stub() if a.llm == "stub" else llmmod.ClaudeCLI(model=a.model or "opus", binary=a.binary)
    cfg = engine.AgentConfig(a.data, lib, robot, llm=llm, workers=1)
    h = Harness(a.data)
    if a.cmd == "show":
        rows = [h.detail(a.step)] if a.step else [h.status(sid) for sid in steps.ORDER]
        for st in rows:
            print(f"{st['step']:8s} protocol v{st['protocol_version']:<4} overlay v{st['overlay_version']:<3} "
                  f"{st['lessons']:2d} lessons  last evolve: "
                  f"{(st.get('last_evolve') or {}).get('decision') or '-'}")
            for r in st.get("experience", []):
                print(f"  {r['kind']:6s} {r['id']:4s} {r.get('cue') or r.get('action') or ''}"
                      f" — {r.get('lesson') or r.get('reason') or ''}")
        return 0
    agent = engine.Agent(cfg)
    if a.cmd == "reflect":
        s = agent.load(a.study)
        if not reached(a.step, s):
            ap.error(f"study {a.study} has not reached the {a.step} step")
        row = reflect(llm, h, a.step, trajectory(a.study, a.step, s, trigger="manual"))
    else:
        row = evolve(agent, llm, llm, a.step, k=a.k, h=h)
    print(json.dumps(row, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
