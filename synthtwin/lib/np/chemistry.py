"""Solution chemistry for the nanoparticle simulator: recipe -> resolved Run.

`setup(params)` turns the simulator params {material, method, conditions,
reagents, calibration?, physics?} into a `Run`: concentrations (mM = mol/m3),
temperature, pH (given, or solved from the charge balance of HAuCl4 acid,
trisodium citrate, NaOH/K2CO3 base and HCl), reductant(s), capping agent(s),
seeds and injection schedule, plus the parameter dict `p` (params.get_params
overlaid with physics overrides and calibration). Also holds the rate laws
growth.py calls each step: reduction rate constants vs T, pH and reductant
level, Au(III) hydrolysis speciation, citrate speciation, Langmuir capping
coverage and water viscosity.

Called by growth.simulate and model.predict.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import brentq

from synthtwin.lib.np import params as P

KB = 1.380649e-23
EV = 1.602176634e-19
R_GAS = 8.314462618
NA = 6.02214076e23

# reagent name -> species (regex over the lowercase name, first match wins)
_SPECIES = [
    ("seed", r"\bseed"),
    ("precursor", r"haucl4|aucl|chloroaur|gold|agno3|silver"),
    ("tannic", r"tannic|tannin"),
    ("borohydride", r"borohydride|nabh4|kbh4"),
    ("ascorbic", r"ascorb"),
    ("citrate", r"citrat|citric"),
    ("pvp", r"pvp|vinyl\s*pyrrolidone"),
    ("ctab", r"ctab|ctac|trimethylammonium"),
    ("base", r"naoh|koh|hydroxide|carbonate|k2co3|na2co3|ammonia"),
    ("acid", r"\bhcl\b|hydrochloric|hno3|nitric"),
]


@dataclass
class Run:
    material: str
    method: str
    T_K: float
    time_s: float
    c_precursor: float                 # total metal over all injections, mM
    reductants: dict[str, float]       # name -> mM (citrate, borohydride, ascorbic, tannic)
    capping: str                       # primary capping agent (CAPPING key)
    c_capping: float                   # mM of a non-citrate capping agent (citrate is tracked)
    pH: float
    n_injections: int = 1
    injection_interval_s: float = 0.0
    preheat_s: float = 0.0
    seed_d_nm: float = 0.0
    seed_cv: float = 0.0
    c_seed: float = 0.0                # metal in seeds, mM
    p: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _species(name: str) -> str | None:
    low = (name or "").lower()
    for sp, pattern in _SPECIES:
        if re.search(pattern, low):
            return sp
    return None


def _num(c: dict[str, Any], key: str) -> float | None:
    v = c.get(key)
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def setup(params: dict[str, Any]) -> Run:
    """Simulator params -> Run (see module docstring)."""
    material = P.canon_material(params.get("material"))
    cond = {k: v for k, v in (params.get("conditions") or {}).items()}
    method = P.canon_method(params.get("method"), cond)
    p = P.get_params(material, method)
    defaults = {k[8:]: v for k, v in p.items() if k.startswith("default_")}
    reagents = {}
    for r in params.get("reagents") or []:
        r = r if isinstance(r, dict) else r.model_dump()
        sp = _species(r.get("name", "")) or (r.get("role") if r.get("role") in ("seed", "base", "acid") else None)
        if sp and sp not in reagents:
            reagents[sp] = r.get("conc_mM")

    def get(key: str) -> float | None:
        v = _num(cond, key)
        return v if v is not None else _num(defaults, key)

    c_p = _num(cond, "conc_precursor_mM") or reagents.get("precursor") or defaults["conc_precursor_mM"]
    c_p = float(c_p)
    # main reductant
    if method in ("citrate", "hot_injection", "tannic"):
        red = "citrate"
    elif method == "borohydride":
        red = "borohydride"
    else:  # seeded: whatever mild reductant the recipe names
        red = next((s for s in ("ascorbic", "citrate", "borohydride") if s in reagents),
                   defaults["reductant"])
    c_red = _num(cond, "conc_reductant_mM")
    if c_red is None and _num(cond, "ratio_reductant_precursor") is not None:
        c_red = _num(cond, "ratio_reductant_precursor") * c_p
    if c_red is None and reagents.get(red) is not None:
        c_red = reagents[red]
    if c_red is None:
        c_red = defaults.get("conc_reductant_mM") or defaults.get("ratio_reductant_precursor", 3.0) * c_p
    reductants = {red: float(c_red)}
    if red != defaults["reductant"]:
        p.update({f"red_{k}": v for k, (v, _s) in P.REDUCTANTS[red].items()})

    # capping agent
    capping = next((s for s in ("pvp", "ctab", "tannic") if s in reagents), None)
    if method == "tannic":
        capping = "tannic"
    if capping is None:
        capping = "citrate" if ("citrate" in reagents or red == "citrate") else defaults["capping"]
    c_cap = _num(cond, "conc_capping_mM")
    if c_cap is None and _num(cond, "ratio_capping_precursor") is not None:
        c_cap = _num(cond, "ratio_capping_precursor") * c_p
    if c_cap is None:
        c_cap = reagents.get(capping)
    if c_cap is None:
        c_cap = defaults.get("conc_capping_mM", 0.0) if capping == defaults["capping"] else 1.0
    c_cap = float(c_cap or 0.0)
    if capping == "tannic":
        reductants["tannic"] = c_cap
    if capping == "citrate" and red != "citrate":
        reductants["citrate_cap"] = c_cap  # citrate present as stabiliser only
    if capping != defaults["capping"]:
        p.update({k: v for k, (v, _s) in P.CAPPING[capping].items()})

    # acid/base and pH
    c_base = _num(cond, "conc_base_mM")
    if c_base is None:
        c_base = reagents.get("base") or defaults.get("conc_base_mM", 0.0)
    c_acid = _num(cond, "conc_acid_mM") or reagents.get("acid") or 0.0
    c_cit = reductants.get("citrate", 0.0) + reductants.get("citrate_cap", 0.0)
    ph = _num(cond, "pH")
    notes: list[str] = []
    if ph is None:
        ph = solve_pH(c_p if material == "Au" else 0.0, c_cit, float(c_base or 0), float(c_acid),
                      p["citrate_pKa"], p["au_hydrolysis_pK"])
        notes.append(f"pH {ph:.2f} from the charge balance")

    # seeds and injections
    method_seeded = method == "seeded"
    seed_d = get("seed_d_nm") if method_seeded else _num(cond, "seed_d_nm")
    c_seed = 0.0
    if seed_d:
        if _num(cond, "conc_seed_mM") is not None:
            c_seed = _num(cond, "conc_seed_mM")
        elif _num(cond, "ratio_seed_precursor") is not None:
            c_seed = _num(cond, "ratio_seed_precursor") * c_p
        elif reagents.get("seed") is not None:
            c_seed = float(reagents["seed"])
        else:
            c_seed = (_num(defaults, "ratio_seed_precursor") or 0.0) * c_p
    n_inj = max(1, int(round(get("n_injections") or 1)))
    time_s = 60.0 * float(get("time_min") or 30.0)
    interval = _num(cond, "injection_interval_min")
    interval_s = 60.0 * interval if interval else time_s / n_inj
    time_s = max(time_s, interval_s * n_inj)

    # physics overrides and calibration (by name)
    for k, v in (params.get("physics") or {}).items():
        p[k] = v
    cal = params.get("calibration") or {}
    p["log10_nuc_prefactor"] += float(cal.get("log10_nucleation_scale", 0.0))
    p["growth_scale"] = 10 ** float(cal.get("log10_growth_scale", 0.0))
    p["rate_scale"] = 10 ** float(cal.get("log10_rate_scale", 0.0))
    c_seed *= 10 ** float(cal.get("log10_seed_scale", 0.0))

    return Run(
        material=material, method=method,
        T_K=273.15 + float(get("temperature_C") if get("temperature_C") is not None else 25.0),
        time_s=time_s, c_precursor=c_p, reductants=reductants, capping=capping,
        c_capping=c_cap, pH=float(ph), n_injections=n_inj, injection_interval_s=interval_s,
        preheat_s=60.0 * float(get("preheat_min") or 0.0) if method == "hot_injection" else 0.0,
        seed_d_nm=float(seed_d or 0.0), seed_cv=float(get("seed_cv_pct") or 8.0) / 100.0,
        c_seed=float(c_seed), p=p, notes=notes,
    )


# ------------------------------------------------------------- speciation
def citrate_fractions(pH: float, pKa=(3.13, 4.76, 6.40)) -> np.ndarray:
    """Fractions of H3Cit, H2Cit-, HCit2-, Cit3- at this pH."""
    h = 10.0 ** -pH
    k = [10.0 ** -x for x in pKa]
    terms = np.array([h ** 3, h ** 2 * k[0], h * k[0] * k[1], k[0] * k[1] * k[2]])
    return terms / terms.sum()


def solve_pH(c_au_acid: float, c_cit: float, c_base: float, c_acid: float,
             pKa=(3.13, 4.76, 6.40), au_pK=(3.3, 6.0, 7.5, 9.0)) -> float:
    """pH from the charge balance (mM): HAuCl4 and HCl are strong acids,
    trisodium citrate brings 3 Na+ per citrate, base is mM of OH- equivalents,
    and each OH- bound by Au(III) hydrolysis releases one H+. The temperature
    shift of pKa is ignored."""
    na = 3.0 * c_cit + c_base

    def balance(ph: float) -> float:
        h = 10.0 ** -ph * 1e3        # mM
        oh = 10.0 ** (ph - 14.0) * 1e3
        a = citrate_fractions(ph, pKa)
        neg = (c_au_acid * (1.0 + au_mean_oh(ph, au_pK)) + c_acid + oh
               + c_cit * (a[1] + 2 * a[2] + 3 * a[3]))
        return h + na - neg

    return float(brentq(balance, 0.0, 14.0))


def au_fractions(pH: float, pK=(3.3, 6.0, 7.5, 9.0)) -> np.ndarray:
    """Fractions of AuCl4-, AuCl3(OH)-, ..., Au(OH)4- (stepwise hydrolysis pK)."""
    logs = np.concatenate([[0.0], np.cumsum([pH - k for k in pK])])
    w = np.exp((logs - logs.max()) * math.log(10.0))
    return w / w.sum()


def au_mean_oh(pH: float, pK=(3.3, 6.0, 7.5, 9.0)) -> float:
    return float(np.dot(au_fractions(pH, pK), np.arange(5)))


def au_reactivity(pH: float, pK=(3.3, 6.0, 7.5, 9.0), rel=(1.0, 0.4, 0.01, 0.001, 0.0001)) -> float:
    """Mean reactivity of Au(III) over AuCl4-, AuCl3(OH)-, ..., Au(OH)4- (J07, W15)."""
    return float(np.dot(au_fractions(pH, pK), rel))


def reductant_activity(model: str, pH: float, pKa=(3.13, 4.76, 6.40)) -> float:
    """Fraction of the reductant in its active form."""
    if model == "citrate":
        a = citrate_fractions(pH, pKa)
        return float(a[3] + 0.3 * a[2] + 0.02 * a[1])
    if model == "phenol":  # gallol pKa ~ 8.5 (assumed); small neutral-form activity
        return float(0.1 + 1.0 / (1.0 + 10.0 ** (8.5 - pH)))
    return 1.0


def arrhenius(Ea_kJ: float, T_K: float, T_ref_C: float) -> float:
    return math.exp(-Ea_kJ * 1e3 / R_GAS * (1.0 / T_K - 1.0 / (273.15 + T_ref_C)))


def water_viscosity(T_K: float) -> float:
    """Pa s, Vogel fit (V24)."""
    return 2.414e-5 * 10.0 ** (247.8 / (T_K - 140.0))


def langmuir_K(dG_eV, T_K: float):
    """Langmuir constant (1/mM) from the adsorption free energy (1 M standard state)."""
    return np.exp(-np.asarray(dG_eV) * EV / (KB * T_K)) / 1000.0


def coverage(K_c) -> np.ndarray:
    """theta = sum K c / (1 + sum K c) for competing adsorbates (K c already summed)."""
    kc = np.asarray(K_c, dtype=float)
    return kc / (1.0 + kc)
