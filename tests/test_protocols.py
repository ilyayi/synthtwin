"""The protocol registry: it validates, it covers the engine, the prompts moved
verbatim (parity with the v1 snapshot taken from the pre-protocol constants),
and studies record which protocol versions they ran under."""
from __future__ import annotations

import json
from pathlib import Path

from synthtwin import protocols
from synthtwin.steps.bench import builder
from synthtwin.steps.prior import prior
from synthtwin.core import engine, toolbox
from synthtwin.core import runner
from synthtwin.ui.server import App

EXAMPLES = Path(__file__).parent.parent / "examples"
SNAPSHOT = json.loads((Path(__file__).parent / "fixtures" / "prompts_v1.json").read_text())


def test_registry_validates() -> None:
    protocols.validate()                                    # raises ValueError naming any problem
    assert protocols.STUDY_PHASES == tuple(engine.ORDER)    # the phase list is the engine's
    for ph in engine.ORDER:                                 # every phase has a protocol
        assert protocols.for_phase(ph), ph
    json.dumps(protocols.manifest())                        # the API payload is JSON-serialisable
    assert {m["id"]: m for m in protocols.manifest()} == {  # manifest = metadata, versions consistent
        pid: p.meta() for pid, p in protocols.load_all().items()}
    assert protocols.versions() == {m["id"]: m["version"] for m in protocols.manifest()}


def test_every_engine_prompt_key_resolves() -> None:
    for key in ("common", *engine.PHASE_SYSTEM):
        assert protocols.prompt(key).strip(), key
    for key in ("builder.brief", "builder.resume", "builder.review",
                "builder.time_limited", "builder.no_limit", "prior.web_system", "toolbox.policy"):
        assert protocols.prompt(key).strip(), key


def test_prompts_moved_verbatim() -> None:
    """The text the LLM receives did not change when it moved into the protocol
    files: every protocol-sourced string equals the v1 snapshot (which was taken
    from the original constants and verified against them)."""
    got = {"engine.common": engine.COMMON, "prior.web_system": prior.WEB_SYSTEM,
           "toolbox.policy": toolbox.POLICY, "builder.brief": builder.BRIEF,
           "builder.resume": builder.RESUME, "builder.review": builder.REVIEW,
           "builder.time_limited": builder.TIME_LIMITED, "builder.no_limit": builder.NO_LIMIT}
    got.update({f"engine.{k}": v for k, v in engine.PHASE_SYSTEM.items()})
    assert set(got) == set(SNAPSHOT), (set(got) ^ set(SNAPSHOT))
    for k in sorted(SNAPSHOT):
        assert got[k] == SNAPSHOT[k], f"prompt {k} differs from the v1 snapshot"


def test_agent_meta_lists_protocols(tmp_path: Path) -> None:
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    from synthtwin.ui.server import make_handler
    cfg = runner.Config(tmp_path / "data", EXAMPLES / "recipes.jsonl", EXAMPLES / "robot.yaml",
                        n_eval=12, predictor="np_stub")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(cfg)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/api/agent", timeout=10) as r:
            meta = json.loads(r.read())
    finally:
        srv.shutdown()
    assert {m["id"]: m["version"] for m in meta["protocols"]} == protocols.versions()


def test_new_study_records_protocol_versions(tmp_path: Path) -> None:
    s = engine.new_study("proto-1", "Au 15 nm by citrate")
    assert s["protocols"] == protocols.versions()


def test_old_study_without_versions_loads_and_renders(tmp_path: Path) -> None:
    cfg = engine.AgentConfig(tmp_path / "data", EXAMPLES / "recipes.jsonl", EXAMPLES / "robot.yaml",
                             n_eval=12, predictor="np_stub")
    old = engine.new_study("old-1", "Au 15 nm by citrate")
    del old["protocols"]                                    # a study saved before protocols existed
    runner.save(cfg.data_dir / "studies" / "old-1.json", old)
    app = App(cfg)
    assert app.get("old-1")["kind"] == "agent"              # loads
    assert app.list()["studies"][0]["id"] == "old-1"        # and renders in the study list
    agent = engine.Agent(cfg)                               # restart over old files: no KeyError
    assert agent.load("old-1")["id"] == "old-1"
