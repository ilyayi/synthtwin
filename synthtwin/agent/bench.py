"""Moved to synthtwin.steps.bench.bench (the bench step's scorer);
this alias keeps imports of the old path working."""
import sys

from synthtwin.steps.bench import bench as _moved

sys.modules[__name__] = _moved
