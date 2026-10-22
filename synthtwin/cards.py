"""Moved to synthtwin.lib.cards; this alias keeps the synthtwin.cards import path working."""
import sys
from synthtwin.lib import cards as _moved
sys.modules[__name__] = _moved
