"""Shared fixtures: three synthetic gold cases each in examples/gold (CO
light-off) and examples/sweep_gold (nanoparticle sweeps) - made-up numbers,
safe to publish - split into card + vault; the design-pipeline stub
predictor (tests/stubs) kept importable for --predictor specs; and the study
agent: the scripted LLM, the agent it drives, settle() and the prompts seen."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Callable

import pytest

from synthtwin.core import engine
from synthtwin.core.llm import Stub, _minimal
from synthtwin.lib.cards import split_gold
from synthtwin.lib.sweep import split_sweep_gold

GOLD_DIR = Path(__file__).parent.parent / "examples" / "gold"
SWEEP_GOLD_DIR = Path(__file__).parent.parent / "examples" / "sweep_gold"

# make tests/stubs/np_stub.py importable as a top-level module, the way the
# CLI loads --predictor package.module
for _entry in (str(Path(__file__).parent / "stubs"),):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)


def load_gold(case_id: str) -> dict:
    return json.loads((GOLD_DIR / f"{case_id}.json").read_text())


def load_sweep_gold(case_id: str) -> dict:
    return json.loads((SWEEP_GOLD_DIR / f"{case_id}.json").read_text())


@pytest.fixture
def case_a():
    return split_gold(load_gold("co-pt-loading-a"))


@pytest.fixture
def case_b():
    return split_gold(load_gold("co-pd-particle-b"))


@pytest.fixture
def case_c():
    return split_gold(load_gold("co-pt-dispersion-c"))


@pytest.fixture
def sweep_a():
    return split_sweep_gold(load_sweep_gold("np-au-citrate-a"))


@pytest.fixture
def sweep_b():
    return split_sweep_gold(load_sweep_gold("np-au-ph-b"))


@pytest.fixture
def sweep_c():
    return split_sweep_gold(load_sweep_gold("np-ag-seed-c"))


# ------------------------------------------------------------ the study agent
EXAMPLES = Path(__file__).parent.parent / "examples"
GOAL = {"material": "Au", "method": "citrate reduction", "title": "Au 15 nm citrate",
        "targets": [{"quantity": "size_mean_nm", "aim": "equal", "value": 15.0}],
        "knobs": [{"key": "ratio_reductant_precursor", "lo": 1.0, "hi": 10.0},
                  {"key": "temperature_C", "lo": 60.0, "hi": 110.0}],
        "fixed": []}
PROMPTS: list[str] = []


def scripted(system: str, prompt: str, schema: dict) -> dict:
    PROMPTS.append(prompt)
    ans = _minimal(schema)
    ans.update(reply="ok", ready=True)
    props = schema.get("properties", {})
    if "problem" in props:
        ans["problem"] = GOAL
    if "studies" in props:   # literature search: one made-up sweep
        ans["studies"] = [{"title": "Made-up Au citrate ratio sweep", "url": "https://example.org/x", "year": "2021",
                           "material": "Au", "method": "citrate reduction", "swept_key": "ratio_reductant_precursor",
                           "fixed": [{"key": "temperature_C", "value": 100}],
                           "points": [{"swept_value": v, "outcomes": [{"quantity": "size_mean_nm", "value": d}]}
                                      for v, d in ((1, 40), (3, 22), (6, 15), (12, 10))],
                           "takeaway": "more citrate, smaller", "confidence": "high"}]
    if "insights" in props:
        ans["insights"] = ["ratio matters most"]
    if "chain" in props:    # the chain the stack implements (one link the scales can point at)
        ans["chain"] = [{"id": "nucleation", "name": "Nucleation", "physics": "a burst of new particles",
                         "inputs": ["precursor"], "outputs": ["N"], "sensitivity": "high",
                         "why": "sets the particle count", "data": "none", "competing": [], "lessons": [],
                         "methods": ["continuum"]}]
    if "scales" in props:   # the three-scale view of the stack, with parts that need cleaning
        ans["scales"] = [
            {"id": "reactor", "title": "R" + "x" * 200, "summary": "the flask and its process",
             "size": "cm", "time": "minutes", "passes_down": "T(t), mixing time",
             "links": ["nucleation", "bogus_link"], "methods": ["continuum", "bogus_method"],
             "processes": [{"name": "Heat", "what": "brings the liquid to reflux", "formula": "dT/dt = 1",
                            "icon": "made_up_icon"}, {"what": "a process with no name"}]},
            {"id": "atomistic", "title": "Atoms", "summary": "the atoms",
             "processes": [{"name": "Coalescence", "what": "small particles merge", "icon": "collide"}]},
            {"id": "galactic", "title": "not a scale", "processes": [{"name": "x", "what": "y"}]}]
    if "recipe" in props:
        ans["recipe"] = {"title": "R", "why": "w", "steps": ["a"], "expected": "15 nm", "checks": ["c"], "risks": ["r"]}
    return ans


@pytest.fixture()
def agent(tmp_path: Path):
    cards, vault = tmp_path / "cards", tmp_path / "vault"
    cards.mkdir(), vault.mkdir()
    for f in sorted((EXAMPLES / "sweep_gold").glob("*.json")):
        card, v = split_sweep_gold(json.loads(f.read_text()))
        (cards / f.name).write_text(card.model_dump_json())
        (vault / f.name).write_text(v.model_dump_json())
    cfg = engine.AgentConfig(tmp_path / "data", EXAMPLES / "recipes.jsonl", EXAMPLES / "robot.yaml", cards,
                             n_eval=12, predictor="np_stub", vault=vault, llm=Stub(scripted), workers=1)
    return engine.Agent(cfg)


def _settle(a: engine.Agent, sid: str, secs: float = 240) -> dict:
    t0 = time.time()
    while time.time() - t0 < secs:
        s = a.load(sid)
        if not s.get("busy"):
            assert not s.get("error"), (s["error"], s.get("error_tb"))
            return s
        time.sleep(0.2)
    raise TimeoutError(sid)




@pytest.fixture()
def prompts() -> list[str]:
    """Every prompt the scripted LLM has seen so far (sealed data must never be among them)."""
    return PROMPTS


@pytest.fixture()
def settle() -> Callable:
    return _settle
