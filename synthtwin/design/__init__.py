"""Moved to synthtwin.lib.design; this alias keeps the synthtwin.design.* import paths working."""
import sys
from synthtwin.lib import design as _moved
sys.modules[__name__] = _moved
