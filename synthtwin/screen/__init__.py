"""Moved to synthtwin.lib.screen; this alias keeps the synthtwin.screen.* import paths working."""
import sys
from synthtwin.lib import screen as _moved
sys.modules[__name__] = _moved
