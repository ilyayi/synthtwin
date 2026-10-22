"""Moved to synthtwin.core.runner; this alias keeps the synthtwin.ui/runner import path working."""
import sys
from synthtwin.core import runner as _moved
sys.modules[__name__] = _moved
