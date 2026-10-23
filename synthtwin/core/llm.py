"""LLM backends for the study agent.

    ClaudeCLI  headless Claude Code (`claude -p`, or any wrapper taking the same
               arguments: a cloud model, a local server) with a JSON schema for
               the answer; uses the signed-in plan, no API key. Tools are off
               unless a call asks for web search (literature search only:
               WebSearch + WebFetch).
    Stub       deterministic answers for tests and offline runs.
    Team       the mix (core.team): a plan backend (frontier) and a work backend
               (light); .role(name) routes, plain backends answer .role() too.

Backends are named in a registry: claude and stub are built in; more come from a
YAML file (schema in docs/models.example.yaml) loaded from --models PATH, else
SYNTHTWIN_MODELS, else ~/.config/synthtwin/models.yaml. Pick one with make(name),
the mix with make_team(plan, work); SYNTHTWIN_LLM overrides the single backend.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

import yaml


class LLMError(RuntimeError):
    pass


BUILTINS = ("Bash,BashOutput,KillShell,Read,Edit,Write,MultiEdit,NotebookEdit,Glob,Grep,LS,Task,Agent,TodoWrite,"
            "WebFetch,WebSearch,Skill,SlashCommand")


def _disallow(allowed: str) -> str:
    """The built-ins minus the allowed ones: with connectors `--tools` cannot be used (it would hide them)."""
    keep = set(allowed.split(","))
    return ",".join(t for t in BUILTINS.split(",") if t not in keep)

# ---------------------------------------------------------------- the registry
# one entry per named backend: the command prefix that replaces `claude`, its
# default model, a UI label, frontier|light, and how to test availability
# (a URL the model server answers, or a command that exits 0; without one, the
# command itself must be on PATH).
BUILTIN_BACKENDS: dict[str, dict] = {
    "claude": {"cmd": ["claude"], "model": "opus", "label": "Claude", "kind": "frontier"},
    "stub": {"cmd": [], "model": "stub", "label": "Stub (tests)", "kind": "light"},
}
DEFAULT_MODELS_FILE = Path("~/.config/synthtwin/models.yaml")


def load_backends(path: str | Path | None = None) -> dict[str, dict]:
    """The named backends: the built-ins plus every entry in the models YAML."""
    out = {k: dict(v) for k, v in BUILTIN_BACKENDS.items()}
    p = Path(path or os.environ.get("SYNTHTWIN_MODELS") or DEFAULT_MODELS_FILE).expanduser()
    if not p.is_file():
        return out
    doc = yaml.safe_load(p.read_text()) or {}
    for name, spec in (doc.get("backends") or {}).items():
        if not isinstance(spec, dict) or not isinstance(spec.get("cmd"), list):
            raise ValueError(f"{p}: backend {name!r} needs a cmd list")
        out[name] = {"model": "opus", "label": name, "kind": "light", **spec}
    return out


def available(spec: dict, timeout: float = 4.0) -> tuple[bool, str]:
    """(ok, reason) whether a backend can run here: its check (URL or command),
    else whether the command is on PATH."""
    chk = spec.get("check")
    if not spec.get("cmd"):
        return True, ""
    try:
        if isinstance(chk, dict) or isinstance(chk, str) and str(chk).startswith(("http://", "https://")):
            url = chk.get("url") if isinstance(chk, dict) else chk
            try:
                urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "synthtwin"}),
                                       timeout=timeout)
            except urllib.error.HTTPError:   # the server answered; that is all we wanted to know
                pass
            return True, ""
        if chk:
            if isinstance(chk, list):   # a command as a list runs as-is; as a string, in a shell
                r = subprocess.run(chk, capture_output=True, text=True, timeout=timeout * 2)
            else:
                r = subprocess.run(str(chk), shell=True, capture_output=True, text=True, timeout=timeout * 2)
            return r.returncode == 0, "" if r.returncode == 0 else (r.stderr.strip() or f"exit {r.returncode}")[-200:]
        exe = spec["cmd"][0]
        return bool(shutil.which(exe)), "" if shutil.which(exe) else f"`{exe}` is not on PATH"
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return False, f"{type(exc).__name__}: {exc}"[:200]


# presets the UI offers: only the ones whose backends are registered appear
PRESETS = [("Claude", "claude", "claude"), ("GLM", "glm", "glm"), ("Local", "local", "local"),
           ("Claude plans · GLM executes", "claude", "glm"),
           ("Claude plans · local executes", "claude", "local"),
           ("GLM plans · local executes", "glm", "local")]


class ClaudeCLI:
    name, label, kind = "claude", "Claude", "frontier"
    _role = "plan"   # stamped by Team.role; recorded in every answer's _meta

    def __init__(self, model: str = "opus", binary: str | None = None, timeout: int = 900,
                 cmd: list[str] | None = None, name: str | None = None, label: str | None = None,
                 kind: str | None = None):
        self.model, self.timeout = model, timeout
        self.cmd = [str(x) for x in cmd] if cmd else [binary or "claude"]   # binary= still works
        for k, v in (("name", name), ("label", label), ("kind", kind)):
            if v:
                setattr(self, k, v)
        # an empty working dir: no project files or project memory leak into the agent's context
        self.cwd = Path(tempfile.gettempdir()) / "synthtwin-agent"
        self.cwd.mkdir(exist_ok=True)

    def role(self, name: str = "plan") -> "ClaudeCLI":
        return self   # a single backend plays every role

    def ask(self, system: str, prompt: str, schema: dict, web: bool = False,
            model: str | None = None, mcp: tuple[str, ...] = ()) -> dict:
        """mcp: connector tools (e.g. a paper index) the agent may call; only those are allowed."""
        tools = "WebSearch,WebFetch" if web else ""
        # connectors load only when asked for; `--tools` would hide them, so then the built-ins are disallowed
        tool_args = ["--tools", tools, "--strict-mcp-config"] if not mcp else ["--disallowedTools", _disallow(tools)]
        cmd = [*self.cmd, "-p", "--model", model or self.model, "--output-format", "json",
               "--no-session-persistence", "--setting-sources", "", *tool_args,
               "--system-prompt", system, "--json-schema", json.dumps(schema)]
        if web or mcp:
            cmd += ["--allowedTools", ",".join(x for x in (tools, *mcp) if x)]
        try:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                               timeout=self.timeout, cwd=self.cwd)
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"agent timed out after {self.timeout} s") from exc
        except FileNotFoundError as exc:
            raise LLMError(f"the `{self.cmd[0]}` CLI is not installed or not on PATH") from exc
        out = r.stdout.strip()
        try:
            data = json.loads(out[: out.rfind("}") + 1]) if out else {}
        except json.JSONDecodeError:
            data = {}
        if r.returncode or data.get("is_error") or not isinstance(data.get("structured_output"), dict):
            msg = data.get("result") or r.stderr.strip()[-400:] or out[-400:] or f"exit {r.returncode}"
            raise LLMError(f"agent call failed: {msg}")
        res = data["structured_output"]
        res["_meta"] = {"cost_usd": data.get("total_cost_usd"), "ms": data.get("duration_ms"), "llm": self.name,
                        "model": model or self.model, "role": self._role}
        return res


    def build(self, prompt: str, cwd: Path, timeout: int | None, model: str | None = None,
              schema: dict | None = None, tools: str | None = None, mcp: tuple[str, ...] = ()) -> dict:
        """Claude Code with tools, working in cwd (writes and runs the simulations; timeout None = no limit).

        With a schema the final answer is structured and returned under "data" (used by the QA reviewer).
        mcp: connector tools (the paper index) it may call besides the built-ins."""
        tools = tools or "Bash,Read,Write,Edit,Glob,Grep,WebSearch,WebFetch"
        tool_args = ["--strict-mcp-config", "--tools", tools] if not mcp else ["--disallowedTools", _disallow(tools)]
        cmd = [*self.cmd, "-p", "--model", model or self.model, "--output-format", "json",
               "--no-session-persistence", "--setting-sources", "", *tool_args,
               "--permission-mode", "acceptEdits", "--allowedTools", ",".join((tools, *mcp))]
        if schema:
            cmd += ["--json-schema", json.dumps(schema)]
        try:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"the builder ran out of time ({(timeout or 0) // 60} min)") from exc
        out = r.stdout.strip()
        try:
            data = json.loads(out[: out.rfind("}") + 1]) if out else {}
        except json.JSONDecodeError:
            data = {}
        if r.returncode or data.get("is_error"):
            raise LLMError(f"builder failed: {data.get('result') or r.stderr.strip()[-400:] or f'exit {r.returncode}'}")
        return {"text": data.get("result", ""), "cost_usd": data.get("total_cost_usd"), "ms": data.get("duration_ms"),
                "turns": data.get("num_turns"), "data": data.get("structured_output"),
                "llm": self.name, "model": model or self.model, "role": self._role}


class Stub:
    """Answers from a function of (system, prompt, schema); default: minimal valid answers."""
    name = "stub"
    label, kind = "Stub (tests)", "light"
    _role = "plan"

    def __init__(self, fn: Callable[[str, str, dict], dict] | None = None,
                 builder: Callable[[str, Path], dict] | None = None,
                 reviewer: Callable[[str, Path], dict] | None = None):
        self.fn, self.builder, self.reviewer = fn, builder, reviewer

    def role(self, name: str = "plan") -> "Stub":
        return self

    def ask(self, system: str, prompt: str, schema: dict, web: bool = False, model: str | None = None,
            mcp: tuple[str, ...] = ()) -> dict:
        out = self.fn(system, prompt, schema) if self.fn else _minimal(schema)
        if isinstance(out, dict):
            out.setdefault("_meta", {"cost_usd": 0, "ms": 0, "llm": self.name, "model": self.name,
                                     "role": self._role})
        return out


    def build(self, prompt: str, cwd: Path, timeout: int | None, model: str | None = None,
              schema: dict | None = None, tools: str | None = None, mcp: tuple[str, ...] = ()) -> dict:
        if schema:   # the QA reviewer
            data = self.reviewer(prompt, Path(cwd)) if self.reviewer else {
                "overall": "pass", "summary": "stub review", "methods": [], "model": {"verdict": "pass", "issues": []}}
            return {"text": "", "data": data, "llm": self.name, "model": self.name, "role": self._role}
        if not self.builder:
            raise LLMError("the stub has no builder")
        out = self.builder(prompt, Path(cwd))
        for k, v in (("llm", self.name), ("model", self.name), ("role", self._role)):
            out.setdefault(k, v)
        return out


def _minimal(schema: dict) -> Any:
    t = schema.get("type")
    if t == "object":
        return {k: _minimal(v) for k, v in schema.get("properties", {}).items() if k in schema.get("required", [])}
    if t == "array":
        return []
    if "enum" in schema:
        return schema["enum"][0]
    return {"string": "", "number": 0, "integer": 0, "boolean": False}.get(t)


def _backend(name: str, model: str | None, path: str | Path | None):
    reg = load_backends(path)
    if name == "stub":
        return Stub()
    if name not in reg:
        raise ValueError(f"unknown LLM backend {name!r} (have: {' | '.join(sorted(reg))})")
    spec = reg[name]
    return ClaudeCLI(model=model or os.environ.get("SYNTHTWIN_LLM_MODEL") or spec.get("model") or "opus",
                     cmd=spec["cmd"], name=name, label=spec.get("label", name), kind=spec.get("kind", "frontier"))


def make(name: str | None = None, model: str | None = None, path: str | Path | None = None):
    """One backend by name; its registry entry supplies the command, model and label."""
    name = os.environ.get("SYNTHTWIN_LLM") or name or "claude"
    return _backend(name, model, path)


def make_team(plan: str | None = None, work: str | None = None, model: str | None = None,
              path: str | Path | None = None):
    """The mix: `plan` (agent turns, reviews, splits) over `work` (builders, searches).
    The same name for both is just that backend, so a single-backend setup behaves as ever."""
    from synthtwin.core.team import Team
    plan = plan or "claude"
    work = work or plan
    if plan == work:
        return _backend(plan, model, path)
    return Team(_backend(plan, model, path), _backend(work, None, path))
