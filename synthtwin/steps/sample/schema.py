"""The sample step's LLM schema: which related studies the agent picks for the
benchmark sample."""
from __future__ import annotations

from synthtwin import steps

SCHEMAS = {"sample": steps.llm_schema({"selected": {"type": "array", "items": {"type": "string"}}}, ["selected"])}
