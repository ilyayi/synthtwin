"""The prior step's LLM schema: the search query it may propose for a sharper
literature search."""
from __future__ import annotations

from synthtwin import steps

SCHEMAS = {"prior": steps.llm_schema({"search": {"type": "string"}}, ["search"])}
