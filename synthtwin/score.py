"""Moved to synthtwin.lib.score; this alias keeps the synthtwin.score import path working."""
import sys
from synthtwin.lib import score as _moved
sys.modules[__name__] = _moved
