"""Moved to synthtwin.steps.bench.builder (the bench step's builder agent);
this alias keeps imports of the old path working."""
import sys

from synthtwin.steps.bench import builder as _moved

sys.modules[__name__] = _moved
