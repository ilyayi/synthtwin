"""Simulation visuals served under /viz/: files from one directory (no ..,
known types only) plus a manifest (a JSON list of {file, poster, study, link,
scale, title, caption, kind, source}) re-read whenever its mtime changes."""
from __future__ import annotations

import json
import threading
from pathlib import Path

VIZ_CT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".mp4": "video/mp4",
          ".webm": "video/webm", ".json": "application/json"}


class Viz:
    """One visual directory: its files and its manifest (see the module docstring)."""

    def __init__(self, root: str | Path | None):
        self.root = Path(root).expanduser().resolve() if root else None
        self.lock = threading.Lock()
        self._mtime: float | None = None
        self._items: list[dict] = []

    def path(self, rel: str) -> Path | None:
        """A file inside the visual dir (and only there, with a served extension), else None."""
        if not self.root:
            return None
        p = (self.root / rel).resolve()
        if self.root not in p.parents or p.suffix.lower() not in VIZ_CT or not p.is_file():
            return None
        return p

    def items(self) -> list[dict]:
        if not self.root:
            return []
        f = self.root / "manifest.json"
        try:
            mtime = f.stat().st_mtime
        except OSError:                                # no manifest: nothing to show yet
            with self.lock:
                if self._mtime is not None:
                    self._mtime, self._items = None, []
            return []
        with self.lock:
            if mtime != self._mtime:                   # re-read only when it changed
                try:
                    self._items = [x for x in json.loads(f.read_text()) if isinstance(x, dict)]
                except (json.JSONDecodeError, OSError):
                    self._items = []
                self._mtime = mtime
            return self._items
