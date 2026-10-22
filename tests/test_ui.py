"""Smoke tests for the study UI server on the examples (stub predictor)."""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "stubs"))

from synthtwin.core import runner
from synthtwin.ui.server import App, make_handler
from synthtwin.ui.stages import STAGE_IDS

EXAMPLES = Path(__file__).parent.parent / "examples"
PROBLEM = {"material": "Au", "text": "Au near 15 nm", "methods": ["citrate reduction"],
           "targets": {"size_mean_nm": {"value": 15.0}},
           "knobs": {"ratio_reductant_precursor": [1.0, 10.0], "temperature_C": [60.0, 110.0]},
           "fixed": {}, "n_proposals": 2}


@pytest.fixture()
def base(tmp_path: Path):
    cfg = runner.Config(tmp_path / "data", EXAMPLES / "recipes.jsonl", EXAMPLES / "robot.yaml",
                        n_eval=12, predictor="np_stub")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(cfg)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", cfg
    srv.shutdown()


def call(url: str, body: dict | None = None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read()) if "json" in r.headers["Content-Type"] else r.read()
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def wait(url: str, sid: str, secs: float = 240) -> dict:
    t0 = time.time()
    while time.time() - t0 < secs:
        _, s = call(f"{url}/api/studies/{sid}")
        if s["status"] in ("awaiting_user", "complete", "failed"):
            return s
        time.sleep(0.5)
    raise TimeoutError(sid)


def test_static_and_meta(base) -> None:
    url, _ = base
    code, page = call(url + "/")
    assert code == 200 and b"SynthTwin" in page
    assert call(url + "/static/theme.css")[0] == 200
    assert call(url + "/static/../server.py")[0] == 404
    _, p = call(url + "/api/pipeline")
    assert [s["id"] for s in p["stages"]] == STAGE_IDS
    _, v = call(url + "/api/viz")                       # no --viz: off, but the route answers
    assert v == {"enabled": False, "items": []}
    _, lst = call(url + "/api/studies")
    assert any(c["id"] == "np-au-ag" for c in lst["cases"])   # shipped case study
    assert call(url + "/api/studies/NOT_AN_ID")[0] == 404


PNG = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 64
MP4 = b"\x00\x00\x00\x18ftypmp42" + bytes(range(256))


@pytest.fixture()
def vizbase(tmp_path: Path):
    d = tmp_path / "viz"
    d.mkdir()
    (d / "a.png").write_bytes(PNG)
    (d / "b.mp4").write_bytes(MP4)
    (d / "manifest.json").write_text(json.dumps([
        {"file": "b.mp4", "poster": "a.png", "study": "gold", "scale": "atomistic", "link": "growth",
         "title": "Au coalescence", "caption": "MD of two particles merging", "kind": "result",
         "source": "gold/md.py"}]))
    cfg = runner.Config(tmp_path / "data", EXAMPLES / "recipes.jsonl", EXAMPLES / "robot.yaml",
                        n_eval=4, predictor="np_stub")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(cfg, viz=d)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", d
    srv.shutdown()


def fetch(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_viz_manifest_and_files(vizbase) -> None:
    url, _ = vizbase
    code, m = call(url + "/api/viz")                    # the manifest is served as items
    assert code == 200 and m["enabled"] and m["items"][0]["file"] == "b.mp4"
    code, hdr, body = fetch(url + "/viz/a.png")         # a file, with its content type
    assert code == 200 and body == PNG and hdr["Content-Type"] == "image/png"
    assert hdr["Accept-Ranges"] == "bytes"
    code, hdr, body = fetch(url + "/viz/b.mp4", {"Range": "bytes=4-11"})   # seekable video
    assert code == 206 and body == MP4[4:12]
    assert hdr["Content-Range"] == f"bytes 4-11/{len(MP4)}" and hdr["Content-Type"] == "video/mp4"
    code, _, body = fetch(url + "/viz/b.mp4", {"Range": "bytes=-8"})       # a suffix range
    assert code == 206 and body == MP4[-8:]
    assert fetch(url + "/viz/nope.png")[0] == 404
    assert fetch(url + "/viz/secret.txt")[0] == 404     # only png/jpg/mp4/webm/json are served
    assert fetch(url + "/viz/" + "a" * 99)[0] == 404


def test_viz_no_traversal(vizbase) -> None:
    url, d = vizbase
    (d.parent / "secret.py").write_text("x = 1")
    for p in ("../secret.py", "a.png/../../secret.py", "sub/../../secret.py"):
        assert fetch(url + "/viz/" + p)[0] == 404
    assert (d.parent / "secret.py").read_text() == "x = 1"


def test_study_flows_to_robot_feedback(base) -> None:
    url, cfg = base
    code, r = call(url + "/api/studies", {"title": "Au 15 nm", "problem": dict(PROBLEM)})
    assert code == 201
    s = wait(url, r["id"])
    st = {x["id"]: x for x in s["stages"]}
    assert s["status"] == "awaiting_user", [(x["id"], x["status"], x.get("error")) for x in s["stages"]]
    assert all(st[i]["status"] in ("done", "warn") for i in STAGE_IDS[:6])
    assert st["A7"]["status"] == "awaiting_user" and len(s["proposals"]) == 2
    a1 = {d["q"]: d["a"] for d in st["A1"]["decisions"]}
    assert "temperature_C [60, 110] -> [60, 100]" in a1["Knobs clipped to the robot"]
    assert "total_volume_ml=20" in a1["Unset conditions"]
    assert all(p["conditions"]["temperature_C"] <= 100 for p in s["proposals"])
    a, b = s["proposals"]
    assert call(f"{url}/api/studies/{r['id']}/decide", {"proposal_id": a["id"], "decision": "maybe"})[0] == 400
    assert call(f"{url}/api/studies/{r['id']}/decide", {"proposal_id": a["id"], "decision": "approve"})[0] == 200
    assert call(f"{url}/api/studies/{r['id']}/result", {"proposal_id": b["id"], "measured": {"size_mean_nm": 9}})[0] == 400
    assert call(f"{url}/api/studies/{r['id']}/decide", {"proposal_id": b["id"], "decision": "reject", "note": "no"})[0] == 200
    _, s = call(f"{url}/api/studies/{r['id']}")
    assert {x["id"]: x["status"] for x in s["stages"]}["A8"] == "awaiting_user"
    assert call(f"{url}/api/studies/{r['id']}/result", {"proposal_id": a["id"], "measured": {"size_mean_nm": 14.2}})[0] == 200
    _, s = call(f"{url}/api/studies/{r['id']}")
    assert s["status"] == "complete"
    fb = [json.loads(x) for x in (cfg.data_dir / "feedback.jsonl").read_text().splitlines()]
    assert fb[0]["source"] == "robot" and fb[0]["outcomes"][0]["value"] == 14.2
