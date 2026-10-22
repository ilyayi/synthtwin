"""Moved to synthtwin.lib.atomistic; this alias keeps the synthtwin.atomistic.* import paths working."""
import sys
from synthtwin.lib import atomistic as _moved
sys.modules[__name__] = _moved
