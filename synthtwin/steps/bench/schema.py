"""The bench step's LLM schema: which variant verdict the agent highlights."""
from __future__ import annotations

from synthtwin import steps
from synthtwin.steps.bench.bench import VARIANTS

SCHEMAS = {"bench": steps.llm_schema({"variant": {"type": "string", "enum": list(VARIANTS)}}, ["variant"])}
