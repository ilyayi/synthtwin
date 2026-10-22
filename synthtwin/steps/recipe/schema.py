"""The recipe step's LLM schema: the chosen proposal and the lab recipe the
agent writes up."""
from __future__ import annotations

from synthtwin import steps

SCHEMAS = {"recipe": steps.llm_schema({"choice": {"type": "string"}, "recipe": {"type": "object", "properties": {
    "title": {"type": "string"}, "why": {"type": "string"}, "steps": {"type": "array", "items": {"type": "string"}},
    "expected": {"type": "string"}, "checks": {"type": "array", "items": {"type": "string"}},
    "risks": {"type": "array", "items": {"type": "string"}}, "alternatives": {"type": "string"}},
    "required": ["title", "why", "steps", "expected", "checks", "risks"]}}, ["choice", "recipe"])}
