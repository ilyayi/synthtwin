"""Moved to synthtwin.lib.vault; this alias keeps the synthtwin.vault import path working."""
import sys
from synthtwin.lib import vault as _moved
sys.modules[__name__] = _moved
