"""Screener tests: metric extraction, the scan funnel, family ranking, the deep
pass and the /api/screen endpoints — all against a handwritten ~15-row index
(3 families, 2 metrics, unicode units, a range, an out-of-range number, an
exclude word)."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from synthtwin.core import engine
from synthtwin.core.llm import Stub
from synthtwin.lib.screen import metrics as mm
from synthtwin.lib.screen import scan as sc
from synthtwin.lib.screen.index import load
from synthtwin.ui.server import App, make_handler

EXAMPLES = Path(__file__).parent.parent / "examples"


def _row(material, title, abstract, doi, year, method="solution-based", n_cond=2):
    return {"id": hashlib.sha1(f"{doi}|{material}|{title}".encode()).hexdigest()[:12],
            "material": material, "category": "semiconductors & electronic", "method": method,
            "title": title, "abstract": abstract, "doi": doi, "url": f"https://example.org/{doi}",
            "year": year, "n_steps": 4, "n_cond": n_cond,
            "reagents": ["lead iodide", "cesium iodide"], "src": "omg24"}


ROWS = [
    _row("CsPbI3 thin films", "Efficient CsPbI3 perovskite solar cells",
         "All-inorganic CsPbI3 perovskite solar cells with a power conversion efficiency of 19.5%.", "10.1/a", 2023),
    _row("CsPbI3", "CsPbI3 perovskite solar cell with high PCE",
         "The CsPbI3 perovskite solar cell reaches a PCE of 21.0% after surface passivation.", "10.1/b", 2024),
    _row("CsPbI3 powder", "Ambient-processed CsPbI3 perovskite photovoltaics",
         "Devices show an efficiency of 18.2–20.1% when the CsPbI3 powder is annealed.", "10.1/c", 2022),
    _row("CsPbI3", "Questionable CsPbI3 perovskite solar cells",
         "A PCE of 63% is claimed for the CsPbI3 perovskite solar cell.", "10.1/d", 2024, n_cond=3),
    _row("CsPbI3 quantum dots", "Bright CsPbI3 perovskite quantum dots",
         "CsPbI3 perovskite quantum dots with high photoluminescence.", "10.1/e", 2021, n_cond=1),
    _row("MAPbI3 single crystals", "MAPbI3 perovskite solar cells",
         "MAPbI3 perovskite solar cells with a certified PCE of 22.1%.", "10.2/a", 2023, "solid-state", 3),
    _row("MAPbI3 films", "Spin-coated MAPbI3 perovskite solar cells",
         "A PCE of 20.5% for the MAPbI3 perovskite solar cells.", "10.2/b", 2021, "solid-state", 3),
    _row("TiO2 nanoparticles", "TiO2 electron transport layer perovskite solar cells",
         "Perovskite solar cells with a compact TiO2 layer reach a PCE of 16.0%.", "10.3/a", 2024, "hydrothermal", 3),
    _row("TiO2 films", "Mesoporous TiO2 solar cells",
         "Mesoporous TiO2 solar cells; the power conversion efficiency was 15.2%.", "10.3/b", 2020, "hydrothermal", 3),
    _row("TiO2 nanotubes", "TiO2 nanotube anodes for lithium-ion batteries",
         "TiO2 nanotube anodes deliver a reversible capacity of 512 mA h g−1 at 0.1 C.", "10.3/c", 2022, "hydrothermal"),
    _row("TiO2 nanoparticles", "TiO2 anode materials for lithium batteries",
         "The TiO2 anode shows a specific capacity of 890 mAh/g in a lithium battery.", "10.3/d", 2023, "hydrothermal", 1),
    _row("ZnO nanorods", "ZnO UV detectors",
         "ZnO nanorod photodetectors with high responsivity.", "10.4/a", 2019),
    _row("ZnO", "ZnO varistor ceramics", "ZnO varistor ceramics for surge protection.", "10.4/b", 2018),
    _row("TiO2 photocatalyst", "TiO2 photocatalytic dye removal",
         "TiO2 photocatalyst for methylene blue removal under UV light.", "10.3/e", 2021, "hydrothermal", 1),
    _row("TiO2 films", "Graded-doping TiO2 solar cells",
         "Graded-doping TiO2 solar cells show a PCE of 17.3 %.", "10.3/f", 2022, "hydrothermal", 3),
]


@pytest.fixture()
def index_file(tmp_path: Path) -> Path:
    p = tmp_path / "screen-index.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in ROWS), encoding="utf-8")
    return p


PCE = {"material": "perovskite or TiO2", "application": "solar cell"}


def call(url: str, body: dict | None = None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# ------------------------------------------------------------------ metrics
def test_pick_and_extract() -> None:
    assert mm.pick("perovskite solar cell") == "pce"
    assert mm.pick("red LED") == "eqe"                       # ties go to the first metric
    assert mm.pick("CO2 capture with MOFs") == "co2_uptake"
    assert mm.pick("photocatalytic hydrogen production") == "h2_rate"
    assert mm.pick("OER electrocatalyst") == "overpotential"
    assert mm.pick("something new") is None
    vals = mm.extract("The efficiency of 18.2–20.1% was stable.", "pce")
    assert [v["value"] for v in vals] == [20.1]              # ranges: the larger end
    assert all(len(v["snippet"]) <= 160 for v in vals)
    assert mm.extract("a PCE of 63%", "pce") == []           # outside the sane range
    assert mm.extract("reversible capacity of 512 mA h g−1", "capacity")[0]["value"] == 512
    assert mm.extract("ionic conductivity of 1.2 × 10−3 S cm−1", "ionic_conductivity")[0]["value"] == pytest.approx(0.0012)


# ------------------------------------------------------------------ scan
def test_funnel_and_families(index_file: Path) -> None:
    r = sc.scan(load(index_file), PCE)
    assert [(f["label"], f["n"]) for f in r["funnel"]] == [("all", 15), ("material", 13),
                                                           ("application", 9), ("include/exclude", 9),
                                                           ("reports", 8), ("families", 3)]
    assert r["metric"]["key"] == "pce" and r["metric"]["better"] == "max"
    fams = {f["family"]: f for f in r["families"]}
    assert set(fams) == {"cspbi3", "mapbi3", "tio2"}
    assert fams["cspbi3"]["best"]["value"] == 21.0           # the 63% claim was rejected
    assert fams["cspbi3"]["n_reports"] == 3 and fams["cspbi3"]["n_papers"] == 3
    assert fams["mapbi3"]["best"]["value"] == 22.0 + 0.1
    assert fams["tio2"]["best"]["value"] == 17.3 and fams["tio2"]["names"][0] == "TiO2 films"
    assert r["global_best"]["family"] == "mapbi3" and r["global_best"]["value"] == pytest.approx(22.1)
    assert fams["cspbi3"]["components"] == {"record": pytest.approx(21 / 22.1, abs=1e-3),
                                            "data": pytest.approx(0.375, abs=1e-3),
                                            "sim": 1.0, "recent": 1.0}
    assert fams["mapbi3"]["components"]["sim"] == 0.6        # solid-state route
    st = fams["cspbi3"]["study_text"]
    assert "Beat the best reported power conversion efficiency" in st and "21" in st \
           and "3 reports from 3 papers" in st and "10.1/b" in st


def test_family_normalisation() -> None:
    assert sc.norm("CsPbI3 thin films") == "cspbi3"
    assert sc.norm("15 nm Au nanoparticles") == "au"
    assert sc.norm("ZrO2-15 single crystals") == "zro2"
    assert sc.norm("TiO2 nanotubes") == "tio2"


def test_labels_budget_3(index_file: Path) -> None:
    r = sc.scan(load(index_file), PCE)
    labels = [f["label"] for f in r["families"]]
    assert labels.count("exploit") == 2                      # round(3 * (1 - 0.4))
    assert labels.count("explore") == 1                      # mapbi3: 2 reports
    assert [f["family"] for f in r["families"] if f["label"]] != []
    assert all(f["suggest"] for f in r["families"] if f["label"])
    assert not any(f["suggest"] for f in r["families"] if not f["label"])


def test_include_exclude_and_second_metric(index_file: Path) -> None:
    rows = load(index_file)
    r = sc.scan(rows, {"material": "TiO2", "application": "battery", "exclude": "nanotubes"})
    assert [(f["label"], f["n"]) for f in r["funnel"]] == [("all", 15), ("material", 6),
                                                           ("application", 2), ("include/exclude", 1),
                                                           ("reports", 1), ("families", 1)]
    f = r["families"][0]
    assert f["family"] == "tio2" and f["best"]["value"] == 890 and f["best"]["unit"] == "mAh g-1"
    r2 = sc.scan(rows, {"material": "TiO2", "application": "battery", "include": "nanotubes"})
    assert r2["families"][0]["best"]["value"] == 512         # the mA h g−1 spelling
    with pytest.raises(ValueError):
        sc.scan(rows, {"material": "ZnO", "application": "something unmatched"})


def test_rerank_with_new_weights(index_file: Path) -> None:
    r = sc.scan(load(index_file), PCE)
    assert r["families"][-1]["family"] == "mapbi3"           # last under the default weights
    rr = sc.rank(r, weights={"record": 1.0, "data": 0, "sim": 0, "recent": 0})
    assert rr["families"][0]["family"] == "mapbi3"           # record-first puts it on top
    assert rr["families"][0]["score"] == pytest.approx(1.0)
    assert r["families"][0]["family"] == "cspbi3"            # the original result is untouched


def test_refine_drops_rejected_value(index_file: Path) -> None:
    rows = load(index_file)

    def fn(system: str, prompt: str, schema: dict) -> dict:
        assert "mapbi3" in prompt and "abstract" in prompt.lower()
        return {"reviews": [
            {"family": "mapbi3", "value_ok": False, "value": None,
             "why_beatable": "certified champion cell, not a routine result"},
            {"family": "cspbi3", "value_ok": True, "value": None,
             "why_beatable": "21.0 with surface passivation on a reproducible route"}]}

    r = sc.refine(Stub(fn), sc.scan(rows, PCE), rows)
    fams = {f["family"]: f for f in r["families"]}
    assert fams["mapbi3"]["best"]["value"] == 20.5           # fell back to its next report
    assert fams["mapbi3"]["n_reports"] == 1
    assert fams["mapbi3"]["why_beatable"].startswith("certified")
    assert r["global_best"]["value"] == 21.0 and r["global_best"]["family"] == "cspbi3"
    assert fams["cspbi3"]["components"]["record"] == 1.0     # recomputed against the new best
    assert fams["cspbi3"]["study_text"].startswith("Beat the best reported")
    assert r.get("refined") is True


# ------------------------------------------------------------------ server
@pytest.fixture()
def base(tmp_path: Path, index_file: Path):
    cfg = engine.AgentConfig(tmp_path / "data", EXAMPLES / "recipes.jsonl", EXAMPLES / "robot.yaml",
                             None, llm=Stub(), workers=1)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(cfg, str(index_file))))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", cfg, index_file
    srv.shutdown()


def test_screen_meta(base) -> None:
    url, cfg, ix = base
    code, m = call(url + "/api/screen")
    assert code == 200 and m["enabled"] and m["n_rows"] == 15
    assert next(x for x in m["metrics"] if x["key"] == "pce")["unit"] == "%"
    assert m["categories"][0]["name"] == "semiconductors & electronic"
    assert m["examples"] and m["examples"][0]["material"] == "perovskite" \
           and m["examples"][0]["metric"] == "pce"


def test_screen_scan_and_queue(base) -> None:
    url, cfg, ix = base
    code, r = call(url + "/api/screen", {**PCE, "deep": True})
    assert code == 201 and r["id"].startswith("screen-") and len(r["families"]) == 3
    assert r["refined"] is True                              # the stub returns no reviews: values stand
    sid = r["id"]
    assert (cfg.data_dir / "screens" / f"{sid}.json").is_file()
    code, lst = call(url + "/api/screens")
    assert code == 200 and lst[0]["id"] == sid and lst[0]["n_families"] == 3
    code, s = call(url + f"/api/screen/{sid}")
    assert code == 200 and s["queued_studies"] == {}
    code, q = call(url + f"/api/screen/{sid}/queue",
                   {"families": ["cspbi3"], "texts": {"cspbi3": "Beat 21% PCE for CsPbI3, edited."}})
    assert code == 200 and q["queued"]["cspbi3"].startswith("beat-21-pce-for-cspbi3-edited")
    study = json.loads((cfg.data_dir / "studies" / f"{q['queued']['cspbi3']}.json").read_text())
    assert study["kind"] == "agent" and study["text"].endswith("edited.")
    _, s2 = call(url + f"/api/screen/{sid}")
    live = s2["queued_studies"]["cspbi3"]
    assert live["id"] == q["queued"]["cspbi3"] and set(live) >= {"id", "phase", "status", "busy"}
    assert call(url + f"/api/screen/{sid}/queue", {"families": ["nope"]})[0] == 400
    assert call(url + "/api/screen/NOT_AN_ID")[0] == 404


def test_screen_disabled_and_agent_off(tmp_path: Path, index_file: Path) -> None:
    cfg = engine.AgentConfig(tmp_path / "d2", EXAMPLES / "recipes.jsonl", EXAMPLES / "robot.yaml",
                             None, workers=1)               # no llm: the agent is off
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(cfg)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        _, m = call(url + "/api/screen")
        assert m["enabled"] is False and m["n_rows"] == 0 and m["metrics"]
        assert call(url + "/api/screen", PCE)[0] == 400
    finally:
        srv.shutdown()
    app = App(engine.AgentConfig(tmp_path / "d3", EXAMPLES / "recipes.jsonl",
                                 EXAMPLES / "robot.yaml", None, workers=1),
              str(index_file))
    doc = app.screen_run(PCE)
    with pytest.raises(ValueError):                         # queueing needs the agent
        app.screen_queue(doc["id"], {"families": ["cspbi3"]})


def test_index_load_caches_per_mtime(tmp_path: Path) -> None:
    p = tmp_path / "ix.jsonl"
    p.write_text(json.dumps(ROWS[0]) + "\n")
    assert len(load(p)) == 1
    p.write_text("\n".join(json.dumps(r) for r in ROWS) + "\n")
    os.utime(p, (0, 0))                                      # a different mtime forces a re-read
    assert len(load(p)) == 15
