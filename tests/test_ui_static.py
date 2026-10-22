"""The static shell: the files the browser loads in order must not redeclare a
top-level `const`/`let` name (a SyntaxError that kills the whole file's globals and
blanks the page) or a top-level function (the later one silently replaces the earlier,
as screen.js's `legend()` once did to every chart legend).
"""
import re
from pathlib import Path

import synthtwin.ui.server as server

STATIC = Path(server.__file__).parent / "static"


def loaded_scripts() -> list[str]:
    """The sources the browser evaluates, in load order (steps.js = the panels)."""
    html = (STATIC / "index.html").read_text()
    out = []
    for m in re.finditer(r'<script src="/static/([^"]+)"></script>', html):
        out.append((STATIC / m.group(1)).read_text() if m.group(1) != "steps.js"
                   else server.step_assets("panel.js").decode())
    out.append(re.search(r"<script>(.*)</script>\s*</body>", html, re.S).group(1))
    return out


def test_no_duplicate_const_or_let_across_scripts():
    seen: dict[str, str] = {}
    for i, src in enumerate(loaded_scripts()):
        for m in re.finditer(r"^(?:const|let)\s+([A-Za-z_$]+)", src, re.M):
            name = m.group(1)
            assert name not in seen, f"`{name}` declared in script {seen[name]} and again in {i}"
            seen[name] = str(i)


def test_no_duplicate_top_level_function_across_scripts():
    seen: dict[str, str] = {}
    for i, src in enumerate(loaded_scripts()):
        for m in re.finditer(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", src, re.M):
            name = m.group(1)
            assert name not in seen, f"function `{name}` in script {seen[name]} and again in {i}"
            seen[name] = str(i)
