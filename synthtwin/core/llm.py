"""LLM backends for the study agent.

    ClaudeCLI  headless Claude Code (`claude -p`) with a JSON schema for the answer;
               uses the signed-in Claude plan, no API key. Tools are off unless a call
               asks for web search (literature search only: WebSearch + WebFetch).
    Stub       deterministic answers for tests and offline runs.

Pick one with make(name): "claude" (default) or "stub"; SYNTHTWIN_LLM overrides.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable


class LLMError(RuntimeError):
    pass


BUILTINS = ("Bash,BashOutput,KillShell,Read,Edit,Write,MultiEdit,NotebookEdit,Glob,Grep,LS,Task,Agent,TodoWrite,"
            "WebFetch,WebSearch,Skill,SlashCommand")


class ClaudeCLI:
    name = "claude"

    def __init__(self, model: str = "opus", binary: str = "claude", timeout: int = 900):
        self.model, self.binary, self.timeout = model, binary, timeout
        # an empty working dir: no project files or project memory leak into the agent's context
        self.cwd = Path(tempfile.gettempdir()) / "synthtwin-agent"
        self.cwd.mkdir(exist_ok=True)

    def ask(self, system: str, prompt: str, schema: dict, web: bool = False,
            model: str | None = None, mcp: tuple[str, ...] = ()) -> dict:
        """mcp: connector tools (e.g. a paper index) the agent may call; only those are allowed."""
        tools = "WebSearch,WebFetch" if web else ""
        # connectors load only when asked for; `--tools` would hide them, so then the built-ins are disallowed
        tool_args = ["--tools", tools, "--strict-mcp-config"] if not mcp else ["--disallowedTools", BUILTINS]
        cmd = [self.binary, "-p", "--model", model or self.model, "--output-format", "json",
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
            raise LLMError("the `claude` CLI is not installed or not on PATH") from exc
        out = r.stdout.strip()
        try:
            data = json.loads(out[: out.rfind("}") + 1]) if out else {}
        except json.JSONDecodeError:
            data = {}
        if r.returncode or data.get("is_error") or not isinstance(data.get("structured_output"), dict):
            msg = data.get("result") or r.stderr.strip()[-400:] or out[-400:] or f"exit {r.returncode}"
            raise LLMError(f"agent call failed: {msg}")
        res = data["structured_output"]
        res["_meta"] = {"cost_usd": data.get("total_cost_usd"), "ms": data.get("duration_ms"), "llm": self.name}
        return res


    def build(self, prompt: str, cwd: Path, timeout: int | None, model: str | None = None,
              schema: dict | None = None, tools: str | None = None) -> dict:
        """Claude Code with tools, working in cwd (writes and runs the simulations; timeout None = no limit).

        With a schema the final answer is structured and returned under "data" (used by the QA reviewer)."""
        tools = tools or "Bash,Read,Write,Edit,Glob,Grep,WebSearch,WebFetch"
        cmd = [self.binary, "-p", "--model", model or self.model, "--output-format", "json",
               "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config",
               "--permission-mode", "acceptEdits", "--tools", tools, "--allowedTools", tools]
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
                "turns": data.get("num_turns"), "data": data.get("structured_output")}


class Stub:
    """Answers from a function of (system, prompt, schema); default: minimal valid answers."""
    name = "stub"

    def __init__(self, fn: Callable[[str, str, dict], dict] | None = None,
                 builder: Callable[[str, Path], dict] | None = None,
                 reviewer: Callable[[str, Path], dict] | None = None):
        self.fn, self.builder, self.reviewer = fn, builder, reviewer

    def ask(self, system: str, prompt: str, schema: dict, web: bool = False, model: str | None = None,
            mcp: tuple[str, ...] = ()) -> dict:
        if self.fn:
            return self.fn(system, prompt, schema)
        return _minimal(schema)


    def build(self, prompt: str, cwd: Path, timeout: int | None, model: str | None = None,
              schema: dict | None = None, tools: str | None = None) -> dict:
        if schema:   # the QA reviewer
            data = self.reviewer(prompt, Path(cwd)) if self.reviewer else {
                "overall": "pass", "summary": "stub review", "methods": [], "model": {"verdict": "pass", "issues": []}}
            return {"text": "", "data": data}
        if not self.builder:
            raise LLMError("the stub has no builder")
        return self.builder(prompt, Path(cwd))


def _minimal(schema: dict) -> Any:
    t = schema.get("type")
    if t == "object":
        return {k: _minimal(v) for k, v in schema.get("properties", {}).items() if k in schema.get("required", [])}
    if t == "array":
        return []
    if "enum" in schema:
        return schema["enum"][0]
    return {"string": "", "number": 0, "integer": 0, "boolean": False}.get(t)


def make(name: str | None = None, model: str | None = None):
    name = os.environ.get("SYNTHTWIN_LLM") or name or "claude"
    if name == "stub":
        return Stub()
    if name == "claude":
        return ClaudeCLI(model=model or os.environ.get("SYNTHTWIN_LLM_MODEL") or "opus")
    raise ValueError(f"unknown LLM backend {name!r} (claude | stub)")
