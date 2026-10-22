"""CLI end-to-end: ingest the fixture parquet to recipes.jsonl with counts,
then search it with a problem yaml."""
from __future__ import annotations

import pytest

pyarrow = pytest.importorskip("pyarrow")  # optional extra `data`

from synthtwin.lib.recipes import cli  # noqa: E402
from synthtwin.core.schemas import Recipe  # noqa: E402

from test_ingest import citrate_au_row, parquet  # noqa: F401,E402  (fixture)

PROBLEM_YAML = """
problem_id: au-test
text: 8 nm Au by citrate
material: Au
methods: ["citrate reduction"]
targets:
  size_mean_nm: {value: 8.0}
knobs:
  temperature_C: [20.0, 110.0]
  ratio_reductant_precursor: [1.0, 10.0]
"""


def test_ingest_and_search(tmp_path, parquet, capsys):  # noqa: F811
    out = tmp_path / "recipes.jsonl"
    assert cli.main(["ingest", str(parquet), "--out", str(out)]) == 0
    recipes = [Recipe.model_validate_json(l) for l in out.read_text().splitlines()]
    assert len(recipes) == 2
    captured = capsys.readouterr().out
    assert "rows read: 7" in captured
    assert "nanoparticle recipes: 2 (2 duplicates dropped)" in captured
    assert "with size outcomes: 2" in captured
    assert "Au 2" in captured
    assert "with full conditions" in captured

    problem = tmp_path / "problem.yaml"
    problem.write_text(PROBLEM_YAML)
    assert cli.main(["search", str(problem), str(out)]) == 0
    out_lines = capsys.readouterr().out.splitlines()
    assert out_lines[0].startswith("problem au-test: 1 match(es)")
    assert "lematsynth:10.1/au:0" in out_lines[1]
    assert "size_mean_nm 15 vs 8" in out_lines[1]


def test_ingest_creates_parent_dirs(tmp_path, parquet):  # noqa: F811
    out = tmp_path / "nested" / "dir" / "recipes.jsonl"
    assert cli.main(["ingest", str(parquet), "--out", str(out)]) == 0
    assert out.exists()
