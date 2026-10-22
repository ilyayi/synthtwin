"""SynthTwin study UI: a small local web server (stdlib only).

  python -m synthtwin.ui.server --data DIR --library recipes.jsonl --robot robot.yaml \
      [--cards CARDS_DIR] [--scores SCORES_DIR_OR_FILE] [--port 8770]

Binds to 127.0.0.1. Pages: / (case studies, your studies, start a new study) and
#/s/<id> (one study as it flows through A1-A8). Studies are JSON files in
DIR/studies; curated case studies are JSON files in synthtwin/ui/cases and DIR/cases.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from synthtwin import protocols, steps
from synthtwin.core import toolbox
from synthtwin.steps.bench import bench, builder
from synthtwin.core import catalog, engine
from synthtwin.lib.viz import VIZ_CT, Viz
from synthtwin.core import runner
from synthtwin.ui.stages import STAGES

HERE = Path(__file__).parent
STATIC = HERE / "static"


def step_assets(name: str) -> bytes:
    """Every step folder's panel.js / panel.css, concatenated in pipeline order and
    served as one /static/steps.js (or .css) — the panels stay unbundled."""
    return b"\n\n".join((steps.folder(sid) / name).read_bytes()
                         for sid in steps.ORDER if (steps.folder(sid) / name).is_file())
CASES = HERE / "cases"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
CT = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript",
      ".woff2": "font/woff2", ".svg": "image/svg+xml", ".png": "image/png"}

# screener: demo queries we offer when they return enough families on the index
# (ordered so that the first three already succeed on the real LeMat-Synth index)
SCREEN_EXAMPLES = [{"material": "perovskite", "application": "solar cell"},
                   {"material": "cathode", "application": "battery"},
                   {"material": "anode", "application": "battery"},
                   {"material": "quantum dot", "application": "LED"},
                   {"material": "MOF", "application": "CO2 capture"},
                   {"material": "phosphor", "application": "LED"},
                   {"material": "electrocatalyst", "application": "OER"},
                   {"material": "electrolyte", "application": "battery"}]

# form options for a new study
OPTIONS = {
    "materials": ["Au", "Ag"],
    "methods": ["citrate reduction", "seeded growth", "borohydride reduction", "tannic acid reduction"],
    "quantities": {"size_mean_nm": "mean size (nm)", "size_sd_nm": "size SD (nm)",
                   "size_cv_pct": "size CV (%)", "lspr_nm": "LSPR peak (nm)",
                   "dls_z_nm": "DLS z-average (nm)", "dls_pdi": "DLS PDI"},
    "knobs": {"ratio_reductant_precursor": [1.0, 20.0], "temperature_C": [20.0, 110.0],
              "conc_precursor_mM": [0.1, 2.0], "time_min": [5.0, 120.0], "pH": [3.0, 10.0],
              "total_volume_ml": [5.0, 100.0], "ratio_seed_precursor": [0.01, 1.0]},
}


class App:
    def __init__(self, cfg: runner.Config, screen_index: str | None = None, viz: str | Path | None = None,
                 models: str | Path | None = None):
        self.cfg = cfg
        self.studies = cfg.data_dir / "studies"
        self.lock = threading.Lock()
        self.viz = Viz(viz)
        self.agent = engine.Agent(cfg) if getattr(cfg, "llm", None) else None
        self.models_path = models   # models.yaml: named backends beyond claude/stub
        self._avail: tuple[float, dict[str, tuple[bool, str]]] = (0.0, {})
        self.screen_index = Path(screen_index).expanduser() if screen_index else None
        self.screens = cfg.data_dir / "screens"
        self._screen_meta: dict | None = None
        if self.screen_index:
            self.screens.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------- storage
    def path(self, sid: str) -> Path:
        if not ID_RE.match(sid):
            raise KeyError(sid)
        return self.studies / f"{sid}.json"

    def cases(self) -> list[dict]:
        out = {}
        for d in (CASES, self.cfg.data_dir / "cases"):   # data dir overrides the shipped ones
            for f in sorted(d.glob("*.json")) if d.is_dir() else []:
                c = json.loads(f.read_text())
                c["kind"] = "case"
                out[c["id"]] = c
        return list(out.values())

    def list(self) -> dict:
        mine = []
        for f in self.studies.glob("*.json"):
            try:
                s = json.loads(f.read_text())
            except json.JSONDecodeError:
                continue
            mine.append(_brief(s))
        mine.sort(key=lambda s: -s["created"])
        return {"cases": [_brief(c) for c in self.cases()], "studies": mine}

    def get(self, sid: str) -> dict:
        for c in self.cases():
            if c["id"] == sid:
                return c
        return json.loads(self.path(sid).read_text())

    # ---------------------------------------------------------- model mix
    def models(self) -> dict:
        """The named backends with availability, the current plan/work mix and the presets."""
        from synthtwin.core import llm as llmmod
        reg = llmmod.load_backends(self.models_path)
        if time.time() - self._avail[0] > 20:   # availability checks are not free; cache them briefly
            self._avail = (time.time(), {n: llmmod.available(spec) for n, spec in reg.items()})
        ok = self._avail[1]
        cur = self.agent.cfg.llm if self.agent else None
        plan, work = (getattr(cur, r, cur) for r in ("plan", "work"))
        return {"enabled": bool(self.agent), "current": bool(cur),
                "backends": [{"name": n, "label": spec.get("label", n), "kind": spec.get("kind", ""),
                              "model": spec.get("model", ""), "available": ok[n][0], "reason": ok[n][1]}
                             for n, spec in reg.items()],
                "plan": plan.name if cur else None, "work": work.name if cur else None,
                "presets": [{"name": n, "plan": p, "work": w} for n, p, w in llmmod.PRESETS
                            if p in reg and w in reg]}

    def set_models(self, body: dict) -> dict:
        """Switch the mix at runtime (no restart): {plan, work} backend names, work defaulting to plan."""
        from synthtwin.core import llm as llmmod
        if not self.agent:
            raise ValueError("the study agent is off (start the server with --llm)")
        reg = llmmod.load_backends(self.models_path)
        plan, work = body.get("plan"), body.get("work") or body.get("plan")
        for n in filter(None, (plan, work)):
            if n not in reg:
                raise ValueError(f"unknown backend {n!r} (have: {' | '.join(sorted(reg))})")
        with self.lock:
            self.agent.cfg.llm = llmmod.make_team(plan, work, path=self.models_path)
        return self.models()

    # ---------------------------------------------------------- actions
    def create(self, body: dict) -> dict:
        problem = body.get("problem") or {}
        base = re.sub(r"[^a-z0-9]+", "-", (body.get("title") or problem.get("material") or "study").lower()).strip("-")
        sid = f"{base[:40] or 'study'}-{time.strftime('%m%d-%H%M%S')}"
        problem["problem_id"] = sid
        study = runner.new_study(sid, problem, body.get("title", ""))
        if body.get("from_case"):
            study["from_case"] = body["from_case"]
        path = self.path(sid)
        runner.save(path, study)
        threading.Thread(target=runner.run_study, args=(path, self.cfg), daemon=True).start()
        return {"id": sid}

    def decide(self, sid: str, body: dict) -> dict:
        with self.lock:
            path = self.path(sid)
            s = json.loads(path.read_text())
            p = _proposal(s, body.get("proposal_id"))
            if body.get("decision") not in ("approve", "reject"):
                raise ValueError("decision must be approve or reject")
            p["decision"] = {"decision": body["decision"], "note": str(body.get("note", ""))[:500], "at": time.time()}
            props = s.get("proposals") or []
            a7, a8 = _stage(s, "A7"), _stage(s, "A8")
            n_dec = sum(1 for q in props if q.get("decision"))
            approved = [q for q in props if (q.get("decision") or {}).get("decision") == "approve"]
            a7["decisions"].append({"q": f"{p['id']}", "a": body["decision"],
                                    "why": p["decision"]["note"] or "no note"})
            if n_dec == len(props):
                a7.update(status="done", summary=f"{len(approved)} approved, {len(props) - len(approved)} rejected")
                if approved:
                    a8.update(status="awaiting_user",
                              summary=f"{len(approved)} approved proposals wait for robot results "
                                      "(robot integration deferred: enter measurements by hand)")
                    s["status"] = "awaiting_user"
                else:
                    a8.update(status="skipped", summary="Nothing approved")
                    s["status"] = "complete"
            else:
                a7["summary"] = f"{n_dec} of {len(props)} proposals decided"
            runner.save(path, s)
        return {"ok": True}

    def result(self, sid: str, body: dict) -> dict:
        with self.lock:
            path = self.path(sid)
            s = json.loads(path.read_text())
            p = _proposal(s, body.get("proposal_id"))
            if (p.get("decision") or {}).get("decision") != "approve":
                raise ValueError("only approved proposals can get robot results")
            measured = {q: float(v) for q, v in (body.get("measured") or {}).items() if v not in (None, "")}
            if not measured:
                raise ValueError("no measured values")
            rows = []
            for q, v in measured.items():
                b = p["predicted"].get(q)
                inside = b is not None and b["low"] <= v <= b["high"]
                rows.append([p["id"], q, f"{v:g}", "-" if not b else f"{b['value']:.2f} [{b['low']:.2f}, {b['high']:.2f}]",
                             "-" if not b else ("inside band" if inside else "outside band")])
            p["measured"] = measured
            a8 = _stage(s, "A8")
            a8["tables"] = [t for t in a8["tables"] if t["title"] != "Measured vs predicted"]
            prev = [r for r in _rows(s) if r[0] != p["id"]]
            a8["tables"].append({"title": "Measured vs predicted",
                                 "columns": ["proposal", "quantity", "measured", "predicted band", "check"],
                                 "rows": prev + rows})
            # feedback: the result becomes a library recipe (A2) for the next study
            recipe = {"recipe_id": f"robot:{sid}:{p['id']}", "source": "robot", "paper_title": f"robot run {p['id']}",
                      "material": s["problem"]["material"], "method": p["method"], "conditions": p["conditions"],
                      "outcomes": [{"quantity": q, "value": v, "unit": (p["predicted"].get(q) or {}).get("unit", ""),
                                    "method": "robot"} for q, v in measured.items()]}
            with open(self.cfg.data_dir / "feedback.jsonl", "a") as fh:
                fh.write(json.dumps(recipe) + "\n")
            approved = [q for q in s["proposals"] if (q.get("decision") or {}).get("decision") == "approve"]
            done = [q for q in approved if q.get("measured")]
            a8["decisions"].append({"q": f"{p['id']} result", "a": "recorded",
                                    "why": "appended to the library as a robot recipe (feeds A2 of the next study)"})
            if len(done) == len(approved):
                a8.update(status="done", summary=f"{len(done)} results recorded and fed back to the library")
                s["status"] = "complete"
            else:
                a8["summary"] = f"{len(done)} of {len(approved)} approved proposals measured"
            runner.save(path, s)
        return {"ok": True}

    # ---------------------------------------------------------- screener
    def screen_rows(self) -> list[dict]:
        from synthtwin.lib.screen import index as sindex

        if not self.screen_index:
            raise ValueError("the screener is off (start the server with --screen-index)")
        return sindex.load(self.screen_index)

    def screen_meta(self) -> dict:
        from synthtwin.lib.screen import metrics as smetrics
        from synthtwin.lib.screen.scan import scan as sscan

        if not self.screen_index:
            return {"enabled": False, "n_rows": 0, "categories": [], "examples": [],
                    "metrics": _screen_metrics(smetrics)}
        if self._screen_meta is None:
            rows = self.screen_rows()
            cats = {}
            for r in rows:
                cats[r.get("category") or "other"] = cats.get(r.get("category") or "other", 0) + 1
            found, fallback = [], []
            for q in SCREEN_EXAMPLES:   # demo queries that really return families
                try:
                    r = sscan(rows, q)
                except ValueError:
                    continue
                ex = {"material": q["material"], "application": q["application"],
                      "metric": r["metric"]["key"], "n_families": len(r["families"])}
                if ex["n_families"] >= 5:
                    found.append(ex)
                elif ex["n_families"]:
                    fallback.append(ex)
                if len(found) == 3:
                    break
            self._screen_meta = {"enabled": True, "n_rows": len(rows),
                                 "metrics": _screen_metrics(smetrics),
                                 "categories": [{"name": c, "n": n} for c, n in
                                                 sorted(cats.items(), key=lambda kv: -kv[1])[:15]],
                                 "examples": (found + fallback)[:3]}
        return self._screen_meta

    def screen_run(self, body: dict) -> dict:
        from synthtwin.lib.screen.scan import refine, scan as sscan

        rows = self.screen_rows()
        q = {k: body.get(k) for k in ("material", "application", "metric", "include", "exclude")}
        q.update(budget=body.get("budget") or 3, explore=body.get("explore"),
                 weights=body.get("weights"))
        result = sscan(rows, q)
        if body.get("deep"):
            if not self.agent or not self.agent.cfg.llm:
                raise ValueError("the deep pass needs the study agent (start the server with --llm)")
            from synthtwin.core import llm as llmmod

            try:
                result = refine(self.agent.cfg.llm, result, rows)
            except llmmod.LLMError as exc:
                raise ValueError(f"the deep pass failed: {exc}")
        sid = f"screen-{time.strftime('%m%d-%H%M%S')}-{int((time.time() % 1) * 1000):03d}"
        doc = {"id": sid, "created": time.time(), **result}
        (self.screens / f"{sid}.json").write_text(json.dumps(doc, default=str))
        return doc

    def screen_list(self) -> list[dict]:
        out = []
        for f in self.screens.glob("*.json"):
            try:
                sc = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            out.append({"id": sc["id"], "created": sc.get("created", 0), "query": sc.get("query"),
                        "metric": (sc.get("metric") or {}).get("key"),
                        "n_families": len(sc.get("families") or []),
                        "n_queued": len(sc.get("queued") or {})})
        return sorted(out, key=lambda s: -s["created"])

    def screen_get(self, sid: str) -> dict:
        if not ID_RE.match(sid):
            raise KeyError(sid)
        return json.loads((self.screens / f"{sid}.json").read_text())

    def screen_serve(self, sc: dict) -> dict:
        """The screen with each queued study's live phase/status (same read as /api/studies)."""
        out = dict(sc)
        studies = {}
        for fam, sid in (sc.get("queued") or {}).items():
            try:
                s = self.get(sid)
                studies[fam] = {"id": sid, "phase": s.get("phase"), "status": s.get("status"),
                                "busy": s.get("busy"), "title": s.get("title", "")}
            except (KeyError, FileNotFoundError, json.JSONDecodeError):
                studies[fam] = {"id": sid, "missing": True, "phase": None, "status": "missing",
                                "busy": None, "title": ""}
        out["queued_studies"] = studies
        return out

    def screen_queue(self, sid: str, body: dict) -> dict:
        if not self.agent:
            raise ValueError("the study agent is off (start the server with --llm)")
        names = body.get("families") or []
        if not names:
            raise ValueError("pick at least one family")
        with self.lock:
            sc = self.screen_get(sid)
            fams = {f["family"]: f for f in sc.get("families") or []}
            texts = body.get("texts") or {}
            sc.setdefault("queued", {})
            for name in names:
                if name not in fams:
                    raise ValueError(f"unknown family {name!r}")
                text = str(texts.get(name) or fams[name].get("study_text") or "").strip()
                if not text:
                    raise ValueError(f"no study text for {name!r}")
                sc["queued"][name] = self.agent.create(text)["id"]
            (self.screens / f"{sid}.json").write_text(json.dumps(sc, default=str))
        return self.screen_serve(sc)


def _rows(s: dict) -> list:
    for t in _stage(s, "A8")["tables"]:
        if t["title"] == "Measured vs predicted":
            return t["rows"]
    return []


def _stage(s: dict, sid: str) -> dict:
    return next(x for x in s["stages"] if x["id"] == sid)


def _proposal(s: dict, pid: Any) -> dict:
    for p in s.get("proposals") or []:
        if p["id"] == pid:
            return p
    raise KeyError(f"no proposal {pid!r}")


def _screen_metrics(smetrics) -> list[dict]:
    return [{"key": k, "name": m["name"], "unit": m["unit"], "better": m["better"], "apps": m["apps"]}
            for k, m in smetrics.METRICS.items()]


def _brief(s: dict) -> dict:
    if s.get("kind") == "agent":
        pb = s.get("problem") or {}
        return {"id": s["id"], "kind": "agent", "title": s.get("title", s["id"]), "subtitle": "",
                "created": s.get("created", 0), "status": "running" if s.get("busy") else s.get("status", ""),
                "material": pb.get("material", ""), "tags": [], "text": s.get("text", ""), "phase": s.get("phase"),
                "busy": s.get("busy"), "phases": [{"id": k, "status": v.get("status")} for k, v in s["phases"].items()]}
    return {"id": s["id"], "kind": s.get("kind", "study"), "title": s.get("title", s["id"]),
            "subtitle": s.get("subtitle", ""), "created": s.get("created", 0), "status": s.get("status", ""),
            "material": s.get("problem", {}).get("material", ""), "tags": s.get("tags", []),
            "stages": [{"id": x["id"], "status": x["status"]} for x in s.get("stages", [])],
            "text": s.get("problem", {}).get("text", "")}


def make_handler(app: App):
    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj: Any, code: int = 200) -> None:
            self._send(code, json.dumps(obj, default=str).encode(), "application/json")

        def do_GET(self):
            path = self.path.split("?")[0]
            try:
                if path in ("/", "/index.html"):
                    return self._file(STATIC / "index.html")
                if path == "/static/steps.js":
                    return self._send(200, step_assets("panel.js"), "application/javascript")
                if path == "/static/steps.css":
                    return self._send(200, step_assets("panel.css"), "text/css")
                if path.startswith("/static/"):
                    f = (STATIC / path[8:]).resolve()
                    if STATIC.resolve() not in f.parents:
                        raise KeyError(path)
                    return self._file(f)
                if path == "/api/pipeline":
                    return self._json({"stages": STAGES})
                if path == "/api/options":
                    return self._json(OPTIONS)
                if path == "/api/viz":
                    return self._json({"enabled": app.viz.root is not None, "items": app.viz.items()})
                if path.startswith("/viz/"):
                    f = app.viz.path(path[5:])
                    if f is None:
                        raise KeyError(path)
                    return self._viz_file(f)
                if path == "/api/agent":
                    return self._json({"enabled": bool(app.agent), "steps": steps.STEPS,
                                       "quantities": engine.QUANTITIES, "methods": catalog.METHODS,
                                       "variants": bench.VARIANTS, "protocols": protocols.manifest()})
                if path == "/api/models":
                    return self._json(app.models())
                if path == "/api/studies":
                    return self._json(app.list())
                if path == "/api/screen":
                    return self._json(app.screen_meta())
                if path == "/api/screens":
                    return self._json(app.screen_list())
                m = re.match(r"^/api/screen/([a-z0-9-]+)$", path)
                if m:
                    return self._json(app.screen_serve(app.screen_get(m.group(1))))
                m = re.match(r"^/api/studies/([^/]+)$", path)
                if m:
                    return self._json(app.get(m.group(1)))
                m = re.match(r"^/api/agent/([^/]+)/package$", path)
                if m and app.agent:
                    pk = app.agent.load(m.group(1))["phases"]["robot"].get("package")
                    if pk:
                        self.send_response(200)
                        body = json.dumps(pk, indent=1, ensure_ascii=False).encode()
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.send_header("Content-Disposition", f'attachment; filename="{pk["request"]}.package.json"')
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        return self.wfile.write(body)
            except (KeyError, FileNotFoundError):
                pass
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if self.path == "/api/studies":
                    return self._json(app.create(body), 201)
                if self.path == "/api/models":
                    return self._json(app.set_models(body))
                if self.path == "/api/screen":
                    return self._json(app.screen_run(body), 201)
                m = re.match(r"^/api/screen/([a-z0-9-]+)/queue$", self.path)
                if m:
                    return self._json(app.screen_queue(m.group(1), body))
                if self.path == "/api/agent" or re.match(r"^/api/agent/[^/]+/", self.path):
                    if not app.agent:
                        raise ValueError("the study agent is off (start the server with --llm)")
                    if self.path == "/api/agent":
                        return self._json(app.agent.create(body.get("text", "")), 201)
                    m = re.match(r"^/api/agent/([^/]+)/(chat|confirm|retry|result)$", self.path)
                    if not m:
                        raise KeyError(self.path)
                    sid, act = m.groups()
                    if act == "chat":
                        return self._json(app.agent.chat(sid, body.get("text", "")))
                    if act == "retry":
                        return self._json(app.agent.retry(sid))
                    return self._json(getattr(app.agent, act)(sid, body))
                m = re.match(r"^/api/studies/([^/]+)/(decide|result)$", self.path)
                if m:
                    fn = app.decide if m.group(2) == "decide" else app.result
                    return self._json(fn(m.group(1), body))
                self._json({"error": "not found"}, 404)
            except (KeyError, FileNotFoundError) as exc:
                self._json({"error": str(exc)}, 404)
            except (ValueError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, 400)

        def _file(self, f: Path) -> None:
            if not f.is_file():
                raise FileNotFoundError(f)
            self._send(HTTPStatus.OK, f.read_bytes(), CT.get(f.suffix, "application/octet-stream"))

        def _viz_file(self, f: Path) -> None:
            """Serve a visual; Range requests get 206 + the asked-for bytes so <video> can seek."""
            data = f.read_bytes()
            size = len(data)
            code, body, extra = HTTPStatus.OK, data, []
            m = re.match(r"^bytes=(\d*)-(\d*)$", (self.headers.get("Range") or "").strip())
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = min(int(m.group(2)) if m.group(2) else size - 1, size - 1)
                else:                                   # a suffix of the last n bytes
                    start, end = max(0, size - int(m.group(2))), size - 1
                if start > end or start >= size:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                code, body = HTTPStatus.PARTIAL_CONTENT, data[start:end + 1]
                extra = [("Content-Range", f"bytes {start}-{end}/{size}")]
            self.send_response(code)
            for k, v in extra + [("Accept-Ranges", "bytes"), ("Content-Type", VIZ_CT[f.suffix.lower()]),
                                 ("Content-Length", str(len(body))), ("Cache-Control", "max-age=300")]:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

    return H


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="synthtwin-ui")
    root = HERE.parent.parent
    ap.add_argument("--data", default="synthtwin-ui-data", help="where studies are stored")
    ap.add_argument("--library", default=str(root / "examples" / "recipes.jsonl"))
    ap.add_argument("--robot", default=str(root / "examples" / "robot.yaml"))
    ap.add_argument("--cards", help="sweep cards directory (A3)")
    ap.add_argument("--scores", help="*scores.jsonl file or directory from `sweep score` (A5)")
    ap.add_argument("--n-eval", type=int, default=30)
    ap.add_argument("--vault", help="sealed outcomes of the sweep cards (benchmark scoring only)")
    ap.add_argument("--llm", default="claude", help="study agent backend: claude | stub | off, or a name "
                                                    "from the models file")
    ap.add_argument("--llm-work", default=None, help="the work backend of the mix (default: same as --llm)")
    ap.add_argument("--llm-model", default=None)
    ap.add_argument("--models", help="models.yaml naming extra LLM backends (glm, a local server, ...); "
                                     "see docs/models.example.yaml")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--no-web", action="store_true", help="no literature search in the agent")
    ap.add_argument("--triage", choices=["valency"], help="rank papers from a paper index before the literature "
                                                          "scout (needs the connector in the claude CLI); off by default")
    ap.add_argument("--tools", help="tools.yaml: simulation engines the builder may use for other systems "
                                    "(see examples/tools.yaml)")
    ap.add_argument("--build-minutes", type=int, default=0, help="time budget of one simulator build (0 = no limit)")
    ap.add_argument("--toolbox", default="~/synthtwin-tools",
                    help="folder where builder agents may install software (conda envs, source builds)")
    ap.add_argument("--no-install", action="store_true", help="builders may not install software")
    ap.add_argument("--qa-rounds", type=int, default=3, help="QA review rounds after a build (0 = no review)")
    ap.add_argument("--screen-index", help="screener index jsonl (synthtwin.lib.screen index); "
                                           "without it the auto-search is off")
    ap.add_argument("--viz", help="directory of simulation visuals (png/jpg/mp4/webm + manifest.json)")
    ap.add_argument("--port", type=int, default=8770)
    a = ap.parse_args(argv)
    from synthtwin.core import llm as llmmod
    if a.tools:   # a broken tools file would otherwise only surface when a build starts
        from synthtwin.core import toolbox
        try:
            toolbox.tools_text(a.tools)
        except Exception as exc:
            ap.error(f"--tools {a.tools}: {type(exc).__name__}: {exc}")
    try:          # same for the models file and the backend names
        reg = llmmod.load_backends(a.models)
    except Exception as exc:
        src = a.models or os.environ.get("SYNTHTWIN_MODELS") or llmmod.DEFAULT_MODELS_FILE
        ap.error(f"models file {src}: {type(exc).__name__}: {exc}")
    if a.llm != "off" and a.llm not in reg:
        ap.error(f"--llm {a.llm}: unknown backend (have: {' | '.join(sorted(reg))})")
    if a.llm_work and a.llm_work not in reg:
        ap.error(f"--llm-work {a.llm_work}: unknown backend (have: {' | '.join(sorted(reg))})")
    cfg = engine.AgentConfig(a.data, a.library, a.robot, a.cards, a.scores, a.n_eval, vault=a.vault,
                             llm=None if a.llm == "off" else llmmod.make_team(a.llm, a.llm_work, a.llm_model,
                                                                              path=a.models),
                             workers=a.workers, web=not a.no_web, triage=a.triage, tools=a.tools, build_minutes=a.build_minutes,
                             qa_rounds=a.qa_rounds, toolbox=None if a.no_install else a.toolbox)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(App(cfg, a.screen_index, viz=a.viz,
                                                                     models=a.models)))
    print(f"SynthTwin UI on http://127.0.0.1:{a.port}  (data: {cfg.data_dir})")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
