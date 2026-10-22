"""Stub nanoparticle simulator for tests: size_mean_nm = scale * 30 * ratio^-0.7.

make_model() returns an object following the simulator contract
(docs/PIPELINE.md): calibrate(params, outcomes) -> extra params for predict,
predict(params) -> {quantity: {value, low, high, unit}}. Only size_mean_nm is
predicted, and only when the swept variable is ratio_reductant_precursor -
cases sweeping something else get a constant answer, so the CLI can run the
stub over every fixture without key errors.
"""
from __future__ import annotations


class StubNp:
    def __init__(self):
        self.scale = 1.0

    def calibrate(self, params, outcomes):
        r = params.get("ratio_reductant_precursor", 1.0)
        self.scale = outcomes["size_mean_nm"] / (30.0 * r ** -0.7)
        return {"size_scale": self.scale}

    def predict(self, params):
        r = params.get("ratio_reductant_precursor", 1.0)
        s = params.get("size_scale", 1.0) * 30.0 * r ** -0.7
        return {"size_mean_nm": {"value": s, "low": 0.85 * s, "high": 1.15 * s, "unit": "nm"}}


def make_model():
    return StubNp()
