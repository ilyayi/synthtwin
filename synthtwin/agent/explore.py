"""Moved to synthtwin.steps.case.explore (the case step's maps and sweeps);
this alias keeps imports of the old path working."""
import sys

from synthtwin.steps.case import explore as _moved

sys.modules[__name__] = _moved
