"""Moved to synthtwin.lib.recipes; this alias keeps the synthtwin.recipes.* import paths working."""
import sys
from synthtwin.lib import recipes as _moved
sys.modules[__name__] = _moved
