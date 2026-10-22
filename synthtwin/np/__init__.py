"""Moved to synthtwin.lib.np; this alias keeps the synthtwin.np.* import paths working."""
import sys
from synthtwin.lib import np as _moved
sys.modules[__name__] = _moved
