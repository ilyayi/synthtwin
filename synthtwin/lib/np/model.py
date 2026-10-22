"""Nanoparticle simulator (Au/Ag colloids): predict / spectrum / calibrate.

    predict(params)   -> {quantity: {value, low, high, unit}} for size_mean_nm,
                         size_sd_nm, size_cv_pct, lspr_nm, lspr_fwhm_nm,
                         dls_z_nm, dls_pdi
    spectrum(params)  -> UV-vis extinction spectrum, size histogram, time course
    calibrate(params, outcomes, names=None) -> calibration dict

params (design path, synthtwin.lib.design): {material, method, conditions,
reagents, calibration?, physics?, seed?, n_draws?}. conditions use the
schemas.Recipe keys (temperature_C, time_min, pH, ratio_reductant_precursor,
conc_precursor_mM, conc_capping_mM, conc_base_mM, ratio_seed_precursor,
seed_d_nm, n_injections, injection_interval_min, preheat_min, ...); reagents
are {role, name, conc_mM} dicts. Flat params (sweep path, synthtwin.lib.sweep) -
a dict of conditions with the calibration keys at top level and no
"conditions" key - are accepted too; the material then defaults to the
model's (`make_model()` / `au` is Au, `ag` is Ag).

Families (params.canon_method): citrate (Turkevich/Frens), hot_injection
(inverse order), borohydride, seeded (with n_injections), tannic (tannic acid
+ citrate; TA amount as conc_capping_mM). Pipeline: chemistry.setup (recipe,
pH, speciation) -> growth.simulate (nucleation cohorts, growth, coalescence)
-> optics (Mie on the size histogram) and dls (z-average, PDI).

Uncertainty bands: an ensemble of n_draws (default 16) parameter draws,
seeded by params["seed"] (default 0; draw 0 is the nominal set). Assumed
spreads (1 sd): nucleation prefactor 0.5 decade; k1, k2, k_surface 0.15
decade; coalescence efficiency 0.2 decade; capping dG 0.02 eV; intrinsic
width x exp(0.2). value = nominal draw, low/high = 5th/95th percentiles.

Physics overrides hook: params["physics"] = {name: value} replaces entries of
params.get_params(material, method) by name before the run, e.g. values from
an atomistic study. Names (defaults and sources in params.py):
    gamma_J_m2           metal/solution interfacial energy (CNT barrier,
                         critical radius, Gibbs-Thomson)
    Vm_m3_mol            molar volume of the metal
    coalescence_dmax_nm  particles below this diameter coalesce (0 disables)
    coalescence_eff      collision efficiency of uncapped small particles
    capping_dG_eV        adsorption free energy of the capping agent; Langmuir
                         theta = K c / (1 + K c), K = exp(-dG / kT) / (1 M)
    ligand_shell_nm      ligand shell (DLS d_h = d + 2 shell; optical shell)
Any other key of get_params works the same way (e.g. nuc_onset_mM,
k_surface_m_s, red_k1, A_damping, shell_n).

Calibration keys (params["calibration"]): log10_growth_scale (surface growth
velocity), log10_rate_scale (all reduction rate constants),
log10_nucleation_scale (CNT prefactor), log10_seed_scale (seed amount, often
unreported).
"""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy.optimize import least_squares, minimize_scalar

from synthtwin.lib.np import chemistry, dls, growth, optics
from synthtwin.lib.np import params as P

QUANTITIES = ("size_mean_nm", "size_sd_nm", "size_cv_pct", "lspr_nm", "lspr_fwhm_nm", "dls_z_nm", "dls_pdi")
UNITS = {"size_mean_nm": "nm", "size_sd_nm": "nm", "size_cv_pct": "%", "lspr_nm": "nm",
         "lspr_fwhm_nm": "nm", "dls_z_nm": "nm", "dls_pdi": ""}
CAL_KEYS = ("log10_growth_scale", "log10_rate_scale", "log10_nucleation_scale", "log10_seed_scale")
_BOUNDS = {"log10_growth_scale": (-2.5, 2.5), "log10_rate_scale": (-2.0, 2.0),
           "log10_nucleation_scale": (-8.0, 4.0), "log10_seed_scale": (-2.0, 2.0)}
# knobs fitted by default per family: first with one quantity, both with two or more
_DEFAULT_KNOBS = {"seeded": ("log10_seed_scale", "log10_growth_scale"),
                  "borohydride": ("log10_nucleation_scale", "log10_growth_scale")}
# residual scale for calibration: (relative floor, absolute floor)
_FLOOR = {"size_mean_nm": (0.05, 0.3), "size_sd_nm": (0.10, 0.3), "size_cv_pct": (0.10, 1.0),
          "lspr_nm": (0.0, 2.0), "lspr_fwhm_nm": (0.10, 5.0), "dls_z_nm": (0.05, 0.5), "dls_pdi": (0.0, 0.03)}
_NON_CONDITIONS = {"material", "method", "conditions", "reagents", "calibration", "physics", "seed", "n_draws"}


def normalize(params: dict[str, Any], material: str = "Au", method: str | None = None) -> dict[str, Any]:
    """Design-path params pass through; flat (sweep) params are split into
    conditions and calibration."""
    params = dict(params or {})
    if "conditions" in params or "reagents" in params:
        params.setdefault("material", material)
        params.setdefault("method", method)
        return params
    cal = dict(params.get("calibration") or {})
    cond = {}
    for k, v in params.items():
        if k in CAL_KEYS:
            cal[k] = v
        elif k not in _NON_CONDITIONS and isinstance(v, (int, float)) and not isinstance(v, bool):
            cond[k] = float(v)
    return {"material": params.get("material", material), "method": params.get("method", method),
            "conditions": cond, "reagents": [], "calibration": cal, "physics": params.get("physics"),
            "seed": params.get("seed"), "n_draws": params.get("n_draws")}


def _evaluate(params: dict[str, Any], n_draws: int | None = None) -> dict[str, Any]:
    run = chemistry.setup(params)
    n = int(n_draws or params.get("n_draws") or 16)
    seed = params.get("seed")
    if seed is None:
        seed = (params.get("conditions") or {}).get("seed", 0)
    draws = growth.random_draws(n, int(seed))
    res = growth.simulate(run, draws)
    spec = optics.ensemble_spectrum(res["hist"], run.material, run.p)
    lspr, fwhm = optics.peak(spec, run.material)
    z, pdi = dls.z_average(res["hist"], run.material, run.p)
    vals = {"size_mean_nm": res["mean_nm"], "size_sd_nm": res["sd_nm"], "size_cv_pct": res["cv_pct"],
            "lspr_nm": lspr, "lspr_fwhm_nm": fwhm, "dls_z_nm": z, "dls_pdi": pdi}
    return {"run": run, "res": res, "spec": spec, "vals": vals}


def _bands(vals: dict[str, np.ndarray]) -> dict[str, dict[str, Any]]:
    out = {}
    for q in QUANTITIES:
        v = np.asarray(vals[q], dtype=float)
        ok = v[np.isfinite(v)]
        if not len(ok):
            continue
        nominal = float(v[0]) if np.isfinite(v[0]) else float(np.median(ok))
        lo, hi = (np.percentile(ok, [5, 95]) if len(ok) > 1 else (nominal, nominal))
        out[q] = {"value": nominal, "low": float(min(lo, nominal)), "high": float(max(hi, nominal)),
                  "unit": UNITS[q]}
    return out


def predict(params: dict[str, Any], material: str = "Au") -> dict[str, dict[str, Any]]:
    """params -> {quantity: {value, low, high, unit}} (see module docstring)."""
    return _bands(_evaluate(normalize(params, material))["vals"])


def spectrum(params: dict[str, Any], material: str = "Au") -> dict[str, Any]:
    """params -> extinction spectrum (absorbance, 1 cm path) with its 5-95 %
    band, LSPR peak/FWHM, number histogram and the nominal time course."""
    ev = _evaluate(normalize(params, material))
    spec, res = ev["spec"], ev["res"]
    lo, hi = np.percentile(spec, [5, 95], axis=0) if len(spec) > 1 else (spec[0], spec[0])
    return {
        "wavelength_nm": optics.WAVELENGTHS_NM.tolist(), "absorbance": spec[0].tolist(),
        "absorbance_low": np.asarray(lo).tolist(), "absorbance_high": np.asarray(hi).tolist(),
        "lspr_nm": float(ev["vals"]["lspr_nm"][0]), "lspr_fwhm_nm": float(ev["vals"]["lspr_fwhm_nm"][0]),
        "d_centers_nm": growth.D_CENTERS_NM.tolist(), "number_per_m3": res["hist"][0].tolist(),
        "time_course": res["course"], "mass_balance": res["mass_balance"],
        "pH": ev["run"].pH, "method": ev["run"].method, "material": ev["run"].material,
        "notes": ev["run"].notes,
    }


def _outcome_pairs(outcomes: Any) -> list[tuple[str, float, float | None]]:
    if isinstance(outcomes, dict):
        items = [(q, v, None) for q, v in outcomes.items()]
    else:
        items = [(getattr(o, "quantity", None) or o.get("quantity"),
                  getattr(o, "value", None) if not isinstance(o, dict) else o.get("value"),
                  getattr(o, "unc", None) if not isinstance(o, dict) else o.get("unc"))
                 for o in outcomes or []]
    out = []
    for q, v, u in items:
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if q in QUANTITIES and np.isfinite(v) and v > 0:
            out.append((q, v, None if u is None else float(u)))
    return out


def calibrate(params: dict[str, Any], outcomes: Any, names: list[str] | None = None,
              material: str = "Au") -> dict[str, float]:
    """Fit 1-2 nuisance parameters (log10 scales, CAL_KEYS) to measured outcomes
    (list of schemas.Outcome or {quantity: value}) by least squares on the
    nominal draw. Default knobs: log10_growth_scale (+ log10_rate_scale with two
    or more different quantities); seeded: log10_seed_scale (+ growth);
    borohydride: log10_nucleation_scale (+ growth). `names` picks the knobs.
    Returns {} when nothing is usable."""
    obs = _outcome_pairs(outcomes)
    if not obs:
        return {}
    base = normalize(params, material)
    base_cal = dict(base.get("calibration") or {})
    if names is None:
        method = P.canon_method(base.get("method"), base.get("conditions"))
        knobs = _DEFAULT_KNOBS.get(method, ("log10_growth_scale", "log10_rate_scale"))
        names = list(knobs[:2] if len({q for q, _, _ in obs}) >= 2 else knobs[:1])
    names = [n for n in names if n in CAL_KEYS][:2] or ["log10_growth_scale"]
    bounds = np.array([_BOUNDS[n] for n in names], dtype=float)

    def resid(x: np.ndarray) -> np.ndarray:
        p = dict(base)
        p["calibration"] = {**base_cal, **{n: float(v) for n, v in zip(names, x)}}
        vals = _evaluate(p, n_draws=1)["vals"]
        r = []
        for q, v, u in obs:
            rel, ab = _FLOOR[q]
            s = max(rel * abs(v), ab, u or 0.0)
            m = float(vals[q][0])
            r.append((m - v) / s if np.isfinite(m) else 10.0)
        return np.asarray(r)

    if len(names) == 1:
        fit = minimize_scalar(lambda a: float(np.sum(resid(np.array([a])) ** 2)),
                              bounds=tuple(bounds[0]), method="bounded", options={"xatol": 0.01})
        x = np.array([fit.x])
    else:
        x = least_squares(resid, np.zeros(len(names)), bounds=(bounds[:, 0], bounds[:, 1]),
                          diff_step=0.05, xtol=1e-3, max_nfev=40).x
    return {**{k: float(v) for k, v in base_cal.items() if k in CAL_KEYS},
            **{n: round(float(v), 4) for n, v in zip(names, x)}}


class NpModel:
    """Simulator bound to a default material (for flat sweep params)."""

    def __init__(self, material: str = "Au", method: str | None = None):
        self.material, self.method = material, method

    def predict(self, params: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return _bands(_evaluate(normalize(params, self.material, self.method))["vals"])

    def spectrum(self, params: dict[str, Any]) -> dict[str, Any]:
        return spectrum(normalize(params, self.material, self.method))

    def calibrate(self, params: dict[str, Any], outcomes: Any, names: list[str] | None = None) -> dict[str, float]:
        return calibrate(normalize(params, self.material, self.method), outcomes, names)


def make_model(material: str = "Au", method: str | None = None) -> NpModel:
    """Factory for synthtwin.lib.sweep.load_sweep_model("synthtwin.lib.np.model:make_model")."""
    return NpModel(material, method)


au = NpModel("Au")
ag = NpModel("Ag")
