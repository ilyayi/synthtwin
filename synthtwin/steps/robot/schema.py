"""The robot step's LLM schema: measurements are entered by the researcher, so
the agent only converses."""
from __future__ import annotations

from synthtwin import steps

SCHEMAS = {"robot": steps.llm_schema({}, [])}
