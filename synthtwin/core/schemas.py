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


# ------------------------------------------------- general recipes + cases
# Conditions -> measured outcomes, for any solution synthesis (first use: Au/Ag nanoparticles,
# outcomes = size, size distribution, UV-Vis plasmon peak, DLS). The CO light-off types above
# are the first benchmark and stay as they are.

class Reagent(Model):
    role: str                    # precursor | reductant | capping | solvent | base | acid | seed | other
    name: str                    # "HAuCl4", "trisodium citrate", "NaBH4", "PVP", "water"
    conc_mM: float | None = None # concentration in the final mixture when known, else stock
    volume_ml: float | None = None
    amount: str = ""             # as written when it cannot be converted


class Outcome(Model):
    quantity: str                # size_mean_nm | size_sd_nm | size_cv_pct | lspr_nm | lspr_fwhm_nm
                                 # | dls_z_nm | dls_pdi | t50_K | ...
    value: float
    unit: str
    unc: float | None = None     # measurement or reading uncertainty (same unit)
    method: str = ""             # TEM | SEM | DLS | UV-Vis | SAXS | XRD | ...
    basis: str = ""              # number | volume | intensity (for size statistics)
    source: str = ""             # figure/table/text reference


class Recipe(Model):
    """One published (or robot-made) synthesis: reagents + conditions -> outcomes."""
    recipe_id: str               # stable: "<source>:<doi or hash>:<n>"
    source: str                  # "lematsynth" | "case" | "robot" | "manual"
    paper_doi: str = ""
    paper_title: str = ""
    paper_url: str = ""
    published: str = ""
    material: str                # "Au", "Ag", "CdSe", ...
    method: str = ""             # "citrate reduction" | "borohydride reduction" | "seeded growth" | ...
    reagents: list[Reagent] = Field(default_factory=list)
    conditions: dict[str, float] = Field(default_factory=dict)
    # canonical keys: temperature_C, time_min, pH, total_volume_ml, addition_rate_ml_min,
    # stirring_rpm, ratio_<role>_<role> (molar, e.g. ratio_reductant_precursor), conc_<role>_mM
    steps: list[str] = Field(default_factory=list)
    outcomes: list[Outcome] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)   # parameters the paper does not report
    extraction_score: float | None = None


class Band(Model):
    value: float
    low: float
    high: float
    unit: str


class CasePoint(Model):
    label: str                   # legend name in the paper
    value: Any                   # value of the swept variable
    conditions: dict[str, float] = Field(default_factory=dict)   # full conditions at this point
    reagents: list[Reagent] = Field(default_factory=list)


class SweepCase(Model):
    """Benchmark card for a general sweep: what a predictor sees (one anchor point revealed)."""
    case_id: str
    paper_title: str
    paper_url: str
    licence: str
    published: str
    post_cutoff: bool
    material: str
    method: str
    sweep_variable: str          # a conditions key, e.g. "ratio_reductant_precursor"
    quantities: list[str]        # scored outcomes, first is primary (e.g. ["size_mean_nm", "size_cv_pct"])
    points: list[CasePoint]
    steps: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    anchor_label: str
    anchor_outcomes: list[Outcome]


class SweepVault(Model):
    """Sealed measured outcomes for every point. Scorer only."""
    case_id: str
    outcomes: dict[str, list[Outcome]]   # label -> outcomes
    digitised_by: list[str]
    canary: str


class SweepPrediction(Model):
    case_id: str
    predictor: str               # "agent:<model>" | "baseline" | "null"
    points: dict[str, dict[str, Band]]   # label -> quantity -> band


class SweepScore(Model):
    case_id: str
    predictor: str
    quantity: str
    n_points: int                # excluding the anchor
    spearman: float | None
    mae: float
    band_coverage: float
    trend_ok: bool


# ------------------------------------------------------- design pipeline
# problem -> recipe search -> calibrated sim -> optimise -> novelty -> robot proposals.

class Target(Model):
    value: float | None = None   # aim for this
    min: float | None = None
    max: float | None = None
    weight: float = 1.0


class Problem(Model):
    """What the researcher asks for, structured."""
    problem_id: str
    text: str                    # the researcher's words
    material: str
    methods: list[str] = Field(default_factory=list)    # allowed; empty = any in library
    targets: dict[str, Target]   # outcome quantity -> target, e.g. size_mean_nm: {value: 8}
    knobs: dict[str, tuple[float, float]]   # conditions keys the optimiser may vary
    fixed: dict[str, float] = Field(default_factory=dict)   # conditions held constant
    n_proposals: int = 3


class Candidate(Model):
    """One simulated recipe from the optimiser."""
    method: str
    conditions: dict[str, float]
    reagents: list[Reagent] = Field(default_factory=list)
    predicted: dict[str, Band]   # outcome quantity -> band (incl. lspr_nm, dls_z_nm for checking)
    score: float                 # objective value (lower is better)
    label: str | None = None     # "exploit" | "explore" (the 60/40 policy; None = old data)
    in_validated_region: bool
    notes: list[str] = Field(default_factory=list)


class Novelty(Model):
    novel: bool
    nearest_recipe_id: str | None = None
    distance: float | None = None   # normalised; < 1 means "within tolerance of a known recipe"
    coverage: str = "ok"         # "ok" | "thin" (too few library recipes near it to judge)
    reason: str = ""


class Proposal(Model):
    """A robot-ready experiment."""
    proposal_id: str
    problem_id: str
    candidate: Candidate
    novelty: Novelty
    steps: list[str]             # robot-executable steps
    measurements: list[str]      # e.g. "UV-Vis 300-900 nm", "DLS z-average + PDI"
    controls: list[str]          # reference syntheses run alongside (e.g. best known recipe)
    expected: str                # plain-language prediction with bands
    risks: list[str] = Field(default_factory=list)


class RobotProfile(Model):
    """What the synthesis robot can do (examples/robot.yaml; replace with the real one)."""
    name: str
    operations: list[str]        # dispense, heat, stir, age, transfer, measure_uvvis, measure_dls
    reagents: list[str]          # stock solutions available
    temperature_C: tuple[float, float]
    volume_ml: tuple[float, float]
    instruments: list[str]
    batch_size: int
    notes: str = ""
