"""Moved to synthtwin.lib.sweep; this alias keeps the synthtwin.sweep import path working."""
import sys
from synthtwin.lib import sweep as _moved
sys.modules[__name__] = _moved
