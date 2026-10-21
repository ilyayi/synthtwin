"""Shared fixtures: three synthetic gold cases in examples/gold (made-up
numbers, safe to publish) split into card + vault."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from synthtwin.cards import split_gold

GOLD_DIR = Path(__file__).parent.parent / "examples" / "gold"


def load_gold(case_id: str) -> dict:
    return json.loads((GOLD_DIR / f"{case_id}.json").read_text())


@pytest.fixture
def case_a():
    return split_gold(load_gold("co-pt-loading-a"))


@pytest.fixture
def case_b():
    return split_gold(load_gold("co-pd-particle-b"))


@pytest.fixture
def case_c():
    return split_gold(load_gold("co-pt-dispersion-c"))
