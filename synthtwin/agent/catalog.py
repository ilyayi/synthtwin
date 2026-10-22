"""Moved to synthtwin.core.catalog; this alias keeps the synthtwin.agent/catalog import path working."""
import sys
from synthtwin.core import catalog as _moved
sys.modules[__name__] = _moved
