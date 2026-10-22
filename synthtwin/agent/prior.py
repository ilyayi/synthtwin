"""Moved to synthtwin.steps.prior.prior (the prior step's literature scout);
this alias keeps imports of the old path working."""
import sys

from synthtwin.steps.prior import prior as _moved

sys.modules[__name__] = _moved
