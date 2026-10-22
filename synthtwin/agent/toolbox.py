"""Moved to synthtwin.core.toolbox; this alias keeps the synthtwin.agent/toolbox import path working."""
import sys
from synthtwin.core import toolbox as _moved
sys.modules[__name__] = _moved
