"""Moved to synthtwin.lib.baseline; this alias keeps the synthtwin.baseline import path working."""
import sys
from synthtwin.lib import baseline as _moved
sys.modules[__name__] = _moved
