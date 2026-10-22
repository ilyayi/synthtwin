"""Moved to synthtwin.core.schemas; this alias keeps the synthtwin.schemas import path working."""
import sys
from synthtwin.core import schemas as _moved
sys.modules[__name__] = _moved
