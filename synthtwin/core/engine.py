"""The study agent: a chat-driven study that moves through gated phases.

    goal    talk to the researcher until the goal is measurable (targets,
            knobs, fixed conditions); they confirm
    prior   related studies: what was swept, what came out (benchmark cases,
            mined library, agent literature search)
    stack   simulation methods (continuum, MD, DFT, kMC, ...) with time and
            the insight each gives; chat narrows it; they confirm
    sample  related studies with data to benchmark the stack on; they confirm
    bench   the stack predicts the sample (blind where possible) and is scored;
            they approve running their own case
    case    their case: sweeps, 2-D map, sensitivities, optimiser, spectrum
    recipe  the recipe to run and alternatives; they pick one
    robot   offered to the robotic platform; results come back as feedback

Each chat turn calls the LLM with the phase's instructions, the study state
and the recent chat; the answer is a reply plus a structured patch (the
problem, the stack, the sample, ...). Long work runs in background threads;
the study shows `busy` meanwhile. Gold outcomes of benchmark cases are never
sent to the LLM (only scores).
"""
from __future__ import annotations

import json
import re
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable

import yaml

from synthtwin import protocols, steps
from synthtwin.core import catalog, runner, systems, toolbox
from synthtwin.steps.prior import prior

# the pipeline's shape comes from the steps' own step.json files (one source of truth)
ORDER = steps.ORDER
PHASES = [{"id": s["id"], "name": s["name"], "short": s["short"]} for s in steps.STEPS]
QUANTITIES = {"size_mean_nm": "mean core size (nm, TEM)", "size_sd_nm": "size SD (nm)", "size_cv_pct": "size CV (%)",
              "lspr_nm": "LSPR peak (nm, UV-Vis)", "lspr_fwhm_nm": "LSPR width (nm)", "dls_z_nm": "DLS z-average (nm)",
              "dls_pdi": "DLS PDI"}


class AgentConfig(runner.Config):
    def __init__(self, *a, vault: str | Path | None = None, llm: Any = None, workers: int = 6,
                 web: bool = True, tools: str | Path | None = None, build_minutes: int = 0, qa_rounds: int = 3,
                 toolbox: str | Path | None = None, triage: str | None = None, **kw):
        super().__init__(*a, **kw)
        self.vault = Path(vault) if vault else None
        self.llm = llm
        self.workers = workers
        self.web = web
        self.triage = triage                 # paper-index triage before the literature scout (None = off)
        self.tools = Path(tools).expanduser() if tools else None   # tools.yaml: engines the builder may use
        self.build_minutes = build_minutes   # 0 = no time limit
        self.qa_rounds = qa_rounds           # QA review rounds after a build (0 = no review)
        self.toolbox = Path(toolbox).expanduser() if toolbox else None   # builders may install here (None = no installs)


# ---------------------------------------------------------------- prompts
# the text lives in synthtwin/protocols/*.md (one versioned file per protocol); the engine
# keys ("common", "goal", "stack", "stack_other", ...) each resolve to a section there.
COMMON = protocols.prompt("common").replace(
    "{quantities}", "; ".join(f"{k} = {v}" for k, v in QUANTITIES.items())).replace(
    "{condition_keys}", ", ".join(prior.CONDITION_KEYS))

PHASE_SYSTEM = {key: protocols.prompt(key) for key in
                ("goal", "prior", "stack_other", "stack", "sample", "bench", "case", "recipe", "robot")}

# every step's LLM schemas live in its own folder; "stack_other" is the stack
# step's schema for systems with no built-in simulator
SCHEMAS = {k: v for sid in ORDER for k, v in steps.schema(sid).SCHEMAS.items()}


# ---------------------------------------------------------------- records
def new_study(sid: str, text: str) -> dict:
    return {"id": sid, "kind": "agent", "title": text[:70] or sid, "created": time.time(), "status": "running",
            "phase": "goal", "busy": None, "error": None, "text": text,
            "protocols": protocols.versions(),   # which protocol versions this study runs under
            "problem": {}, "chat": [{"role": "user", "text": text, "phase": "goal", "at": time.time()}],
            "phases": {p: {"status": "pending"} for p in ORDER}}


class Agent:
    def __init__(self, cfg: AgentConfig):
        self.cfg = cfg
        self.dir = cfg.data_dir / "studies"
        self.locks: dict[str, threading.Lock] = {}
        self.glock = threading.Lock()
        self.robot = yaml.safe_load(cfg.robot.read_text()) if cfg.robot.is_file() else {}
        self._lib = None
        self._recover()

    def _recover(self) -> None:
        """Jobs do not survive a restart: clear their busy flags so the study can be retried.

        Simulator builds resume by themselves: their detached jobs kept running and the builder
        picks up from its NOTES.md."""
        resume = []
        for f in self.dir.glob("*.json"):
            try:
                s = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if s.get("kind") == "agent" and s.get("busy"):
                building = s.get("phase") == "bench" and not systems.is_builtin(s.get("problem") or {}) \
                    and not (s["phases"]["bench"].get("build") or {}).get("check", {}).get("ok")
                s.update(busy=None, error=f"interrupted by a server restart while {s['busy']}", interrupted=True)
                runner.save(f, s)
                if building and self.cfg.llm is not None:
                    resume.append(s["id"])
        for sid in resume:
            self.retry(sid)

    # ------------------------------------------------------------ storage
    def path(self, sid: str) -> Path:
        if not re.match(r"^[a-z0-9][a-z0-9-]{0,63}$", sid):
            raise KeyError(sid)
        return self.dir / f"{sid}.json"

    def lock(self, sid: str) -> threading.Lock:
        with self.glock:
            return self.locks.setdefault(sid, threading.Lock())

    def load(self, sid: str) -> dict:
        return json.loads(self.path(sid).read_text())

    def mutate(self, sid: str, fn: Callable[[dict], Any]) -> Any:
        with self.lock(sid):
            s = self.load(sid)
            out = fn(s)
            runner.save(self.path(sid), s)
            return out

    def library(self) -> list:
        if self._lib is None:
            from synthtwin.lib.design import run as drun
            lib = drun.load_library(self.cfg.library) if self.cfg.library.is_file() else []
            fb = self.cfg.data_dir / "feedback.jsonl"
            self._lib = lib + (drun.load_library(fb) if fb.exists() else [])
        return self._lib

    def cards(self) -> dict[str, dict]:
        return {c["case_id"]: c for c in prior.load_cards(self.cfg.cards)}

    # ------------------------------------------------------------ background
    def background(self, sid: str, label: str, fn: Callable[[], None]) -> None:
        self.mutate(sid, lambda s: s.update(busy=label, error=None))

        def go():
            try:
                fn()
            except Exception as exc:
                tb = traceback.format_exc(limit=5)
                self.mutate(sid, lambda s: (s.update(error=f"{type(exc).__name__}: {exc}", error_tb=tb),
                                            s["chat"].append({"role": "agent", "phase": s["phase"], "at": time.time(),
                                                              "text": f"Something failed while {label}: {exc}. "
                                                                      "Send a message to retry or rephrase."})))
            finally:
                self.mutate(sid, lambda s: s.update(busy=None))
        threading.Thread(target=go, daemon=True).start()

    def _busy(self, sid: str, label: str) -> None:
        # follow-up work runs in the current background thread; only the label changes
        self.mutate(sid, lambda s: s.update(busy=label))

    # ------------------------------------------------------------ API
    def create(self, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            raise ValueError("describe your problem first")
        base = re.sub(r"[^a-z0-9]+", "-", text.lower())[:36].strip("-") or "study"
        sid = f"{base}-{time.strftime('%m%d-%H%M%S')}"
        n = 1
        while self.path(sid).exists():   # several studies queued in the same second (screener)
            n += 1
            sid = f"{base}-{time.strftime('%m%d-%H%M%S')}-{n}"
        s = new_study(sid, text)
        s["phases"]["goal"]["status"] = "awaiting_user"
        runner.save(self.path(sid), s)
        self.background(sid, "reading your problem", lambda: self.turn(sid))
        return {"id": sid}

    def chat(self, sid: str, text: str) -> dict:
        text = (text or "").strip()[:4000]
        if not text:
            raise ValueError("empty message")
        s = self.load(sid)
        if s.get("busy"):
            raise ValueError(f"the agent is busy ({s['busy']}); wait a moment")
        self.mutate(sid, lambda s: s["chat"].append({"role": "user", "text": text, "phase": s["phase"], "at": time.time()}))
        self.background(sid, "thinking", lambda: self.turn(sid))
        return {"ok": True}

    def confirm(self, sid: str, body: dict) -> dict:
        s = self.load(sid)
        phase = body.get("phase") or s["phase"]
        if s.get("busy"):
            raise ValueError(f"the agent is busy ({s['busy']})")
        if phase != s["phase"]:
            raise ValueError(f"the study is at {s['phase']}, not {phase}")
        confirm = getattr(steps.run(phase), "confirm", None)
        if not confirm:
            raise ValueError(f"nothing to confirm at {phase}")
        confirm(self, sid, s, body)
        return {"ok": True}

    def retry(self, sid: str) -> dict:
        """Re-run the current phase's job (after a failure or a restart), else the agent's turn."""
        s = self.load(sid)
        if s.get("busy"):
            raise ValueError(f"the agent is busy ({s['busy']})")
        ph, P = s["phase"], s["phases"][s["phase"]]
        self.mutate(sid, lambda s: s.update(error=None, interrupted=False))
        if ph == "prior" and not P.get("studies"):
            self.background(sid, "finding related studies", lambda: steps.run("prior").work(self, sid))
        elif ph == "bench" and not P.get("summary"):
            self.background(sid, "benchmarking the stack", lambda: steps.run("bench").work(self, sid))
        elif ph in ("case", "recipe") and not s["phases"]["case"].get("proposals"):
            if ph == "recipe":
                self.mutate(sid, lambda s: s.update(phase="case"))
            self.background(sid, "simulating your case", lambda: steps.run("case").work(self, sid))
        else:
            self.background(sid, "thinking", lambda: self.turn(sid))
        return {"ok": True}

    def result(self, sid: str, body: dict) -> dict:
        return steps.run("robot").result(self, sid, body)

    def context(self, s: dict) -> dict:
        ph = s["phase"]
        ctx: dict[str, Any] = {"phase": ph, "problem": s.get("problem") or None}
        P = s["phases"]
        if P["goal"].get("errors"):
            ctx["goal_errors"] = P["goal"]["errors"]
        if P["prior"].get("studies"):
            ctx["prior"] = [{"id": x["id"], "source": x["source"], "title": x["title"][:120], "year": x.get("year"),
                             "material": x["material"], "method": x["method"],
                             "swept": [{"key": w["key"], "values": w["values"][:12]} for w in x["swept"]],
                             "fixed": x.get("fixed"), "quantities": x.get("quantities"), "relevance": x["relevance"],
                             "takeaway": x.get("takeaway", ""),
                             # benchmark outcomes stay sealed for the LLM
                             "points": f"{len(x['points'])} points, outcomes SEALED until the benchmark scores "
                                       "the simulator (blind test; do not describe them as missing)"
                             if x["source"] == "benchmark" else
                             [{"c": p["conditions"], "o": p["outcomes"]} for p in x["points"][:8]]}
                            for x in P["prior"]["studies"][:14]]
        generic = not systems.is_builtin(s.get("problem") or {})
        if generic and (ph == "stack" or P["stack"].get("methods")):
            ctx["tools"] = toolbox.tools_text(self.cfg.tools, self.cfg.toolbox)
            if P["stack"].get("methods"):
                ctx["stack"] = P["stack"]["methods"]
        elif ph == "stack" or P["stack"].get("methods"):
            ctx["catalog"] = [{k: m[k] for k in ("id", "name", "status", "est", "gives", "helps_when")}
                              | {"available": catalog.available(m, (s.get("problem") or {}).get("material", ""))}
                              for m in catalog.METHODS]
            if P["stack"].get("methods"):
                ctx["stack"] = [{"id": m["id"], "selected": m["selected"]} for m in P["stack"]["methods"]]
        if ph == "sample" and P["sample"].get("candidates"):
            ctx["candidates"] = [{"id": c["id"], "source": c["source"], "title": c["title"][:100],
                                  "swept": c["swept_key"], "points": c["n_points"], "blind": c["blind"],
                                  "relevance": c["relevance"]} for c in P["sample"]["candidates"]]
        if P["bench"].get("build"):
            b = P["bench"]["build"]
            ctx["build"] = {"ok": b["check"]["ok"], "check": b["check"]["out"][-400:], "report": b.get("report"),
                            "summary": b.get("summary", "")[-1200:], "minutes": round(b.get("seconds", 0) / 60, 1),
                            "qa": b.get("qa"), "qa_rounds": b.get("qa_rounds")}
        if P["bench"].get("summary"):
            ctx["bench"] = {"summary": P["bench"]["summary"], "cases": P["bench"]["table"]}
        if P["case"].get("tornado"):
            c = P["case"]
            ctx["case"] = {"tornado": c["tornado"], "center": c["center"], "heatmap": c.get("heat_summary"),
                           "proposals": [{k: p[k] for k in ("id", "conditions", "predicted", "novelty", "steps")}
                                         for p in c.get("proposals", [])],
                           "dropped": c.get("dropped", [])[:4], "basis": c.get("basis")}
        if P["stack"].get("chain"):
            ctx["chain"] = P["stack"]["chain"]
        if P["stack"].get("scales"):
            ctx["scales"] = P["stack"]["scales"]
        return ctx

    def turn(self, sid: str, extra: str = "") -> dict:
        s = self.load(sid)
        ph = s["phase"]
        robot = f"{self.robot.get('name', 'robot')}: T {self.robot.get('temperature_C')} C, volume " \
                f"{self.robot.get('volume_ml')} mL, stocks {', '.join(self.robot.get('reagents', []))}, " \
                f"measures with {', '.join(self.robot.get('instruments', []))}"
        key = "stack_other" if ph == "stack" and not systems.is_builtin(s.get("problem") or {}) else ph
        system = COMMON.replace("{robot}", robot) + "\n" + PHASE_SYSTEM[key].replace("{install}", (
            "Software not in STATE.tools can be installed by the builder (conda-forge, PyPI, source builds): if a \
code would serve a method better (e.g. CP2K, GROMACS-GPU, xtb, OpenMM, an ML potential such as MACE, \
Cantera or OpenMKM for microkinetics, FEniCS, OpenFOAM with OpenQBMM for reactor CFD with a population balance, \
a kMC or phase-field code), name it as the tool, mark it '(install)' and include the install time in est_min." if self.cfg.toolbox
            else "")).replace("{budget}", (
            f"The build has a {self.cfg.build_minutes} min budget: mark methods that would not fit as not selected "
            "and say so." if self.cfg.build_minutes else "There is no time limit: select long atomistic runs "
            "(hours or days) when they supply a parameter that matters; say how long they take."))
        hist = [m for m in s["chat"] if m["role"] in ("user", "agent")][-14:]
        prompt = ("STATE:\n" + json.dumps(self.context(s), default=str)[:60000] + "\n\nCHAT (oldest first):\n"
                  + "\n".join(f"{m['role'].upper()} [{m['phase']}]: {m['text']}" for m in hist)
                  + (f"\n\nNOTE: {extra}" if extra else "") + "\n\nWrite your next turn.")
        # the stack designer may search for simulation studies of similar systems (lessons per chain link);
        # the step's step.json "models" picks plan or work for the turn
        ans = self.cfg.llm.role(steps.role(ph, "turn")).ask(system, prompt, SCHEMAS[key],
                                                            web=bool(self.cfg.web) and ph == "stack")
        meta = ans.pop("_meta", {}) if isinstance(ans, dict) else {}
        follow = self.mutate(sid, lambda s: self.apply(s, ph, ans, meta))
        if follow:
            follow()
        return ans

    def apply(self, s: dict, ph: str, ans: dict, meta: dict) -> Callable | None:
        P = s["phases"][ph]
        P["ready"] = bool(ans.get("ready"))
        follow = steps.run(ph).apply(self, s, ans)
        s["chat"].append({"role": "agent", "text": ans.get("reply", ""), "phase": ph, "at": time.time(),
                          "meta": meta})
        return follow

    # ------------------------------------------------------------ gates
    def _advance(self, s: dict, to: str) -> None:
        s["phases"][s["phase"]]["status"] = "done"
        s["phase"] = to
        s["phases"][to]["status"] = "working"
