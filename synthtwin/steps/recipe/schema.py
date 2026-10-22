"""The recipe step's LLM schema: the chosen proposal and the lab recipe the
agent writes up."""
from __future__ import annotations

from synthtwin import steps

# what the self-building lab needs to stock and set up (the robot step's package)
MATERIALS = {"type": "array", "items": {"type": "object", "properties": {
    "name": {"type": "string"}, "amount": {"type": "string"}, "role": {"type": "string"}}, "required": ["name"]}}
EQUIPMENT = {"type": "array", "items": {"type": "string"}}

SCHEMAS = {"recipe": steps.llm_schema({"choice": {"type": "string"}, "recipe": {"type": "object", "properties": {
    "title": {"type": "string"}, "why": {"type": "string"}, "steps": {"type": "array", "items": {"type": "string"}},
    "expected": {"type": "string"}, "checks": {"type": "array", "items": {"type": "string"}},
    "risks": {"type": "array", "items": {"type": "string"}}, "alternatives": {"type": "string"},
    "materials": MATERIALS, "equipment": EQUIPMENT},
    "required": ["title", "why", "steps", "expected", "checks", "risks", "materials", "equipment"]}}, ["choice", "recipe"])}
