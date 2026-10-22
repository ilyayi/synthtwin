"""Moved to synthtwin.core.engine; this alias keeps the synthtwin.agent/engine import path working."""
import sys
from synthtwin.core import engine as _moved
sys.modules[__name__] = _moved
