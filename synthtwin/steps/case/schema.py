"""The case step's LLM schema: the insights it states and the new knob ranges
it may propose."""
from __future__ import annotations

from synthtwin import steps

SCHEMAS = {"case": steps.llm_schema({"insights": {"type": "array", "items": {"type": "string"}},
                                     "knobs": {"type": "array", "items": {"type": "object", "properties": {
                                         "key": {"type": "string"}, "lo": {"type": "number"},
                                         "hi": {"type": "number"}}, "required": ["key", "lo", "hi"]}}},
                                    ["insights", "knobs"])}
