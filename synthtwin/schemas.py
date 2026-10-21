"""SynthTwin data formats: the case card the predictor sees, the sealed vault
entry, predictions and scores.

Used by every synthtwin module and by any harness that runs predictors on
cases (for example a lab agent that submits a CasePrediction).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    """Base: forbid unknown keys so typos fail loudly."""
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------- SynthTwin
class Catalyst(Model):
    metal: str                   # "Pt" | "Pd" | "Rh" | ...
    support: str
    loading_wt_pct: float | None = None
    particle_nm: float | None = None
    dispersion: float | None = None   # fraction 0-1
    prep: str = ""               # short recipe summary (impregnation, calcination T, ...)


class Feed(Model):
    co_pct: float | None = None
    o2_pct: float | None = None
    other: dict[str, float] = Field(default_factory=dict)   # e.g. {"H2O": 2.0}
    balance: str = "N2"


class SweepPoint(Model):
    label: str                   # legend name in the paper, e.g. "0.5Pt/Al2O3"
    value: Any                   # value of the swept variable
    catalyst: Catalyst


class CaseCard(Model):
    """What the agent sees. Never contains measured outcomes except the anchor point."""
    case_id: str
    paper_title: str
    paper_url: str
    licence: str
    published: str               # ISO date or year
    post_cutoff: bool
    reaction: str = "CO oxidation"
    sweep_variable: str          # e.g. "loading_wt_pct"
    points: list[SweepPoint]
    feed: Feed
    catalyst_mass_mg: float | None = None
    flow_ml_min: float | None = None
    ghsv_per_h: float | None = None
    ramp_K_min: float | None = None
    missing: list[str] = Field(default_factory=list)   # confounders not reported
    anchor_label: str            # the one point whose measurement is revealed
    anchor_t50_K: float          # revealed measurement for calibration


class MeasuredPoint(Model):
    label: str
    t50_K: float
    t50_unc_K: float = 10.0      # digitisation uncertainty
    curve: list[tuple[float, float]] = Field(default_factory=list)   # (T_K, conversion 0-1)
    source: str = ""             # figure/table ref


class VaultEntry(Model):
    """synthtwin/vault/<case_id>.json. Readable by the scorer only; never shown to a predictor."""
    case_id: str
    points: list[MeasuredPoint]
    digitised_by: list[str]      # independent readers that agreed
    canary: str                  # random token; must never appear in agent-visible data


class PointPrediction(Model):
    label: str
    t50_K: float
    low_K: float
    high_K: float


class CasePrediction(Model):
    case_id: str
    points: list[PointPrediction]
    predictor: str               # "agent:<model>" | "baseline" | "null"


class CaseScore(Model):
    case_id: str
    predictor: str
    n_points: int                # excluding the anchor
    spearman: float | None       # rank agreement over all points incl. anchor
    t50_mae_K: float
    band_coverage: float         # fraction of held-out measured T50 inside [low, high]
    trend_ok: bool               # spearman >= 0.8 (or exact order for n<=3)
