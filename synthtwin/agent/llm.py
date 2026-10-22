"""Moved to synthtwin.core.llm; this alias keeps the synthtwin.agent/llm import path working."""
import sys
from synthtwin.core import llm as _moved
sys.modules[__name__] = _moved
