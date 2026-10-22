"""Recipe translations for published Au/Ag one-factor sweeps.

A benchmark card gives each point's swept value and the conditions the paper
states; the simulator needs the full recipe (stock dilutions, seed cycles,
bases). recipe(case_id, value, ...) builds it from the paper's methods section
only (no measured outcomes). Unknown cases fall back to generic(): the point's
conditions and reagents as given.
"""
from __future__ import annotations

from typing import Any, Callable

AU, AG = "HAuCl4", "AgNO3"


def rg(name: str, role: str, c: float | None) -> dict:
    return {"role": role, "name": name, "conc_mM": c}


# Piella et al. 2016 (Chem. Mater. 28, 1066): 150 mL citrate 2.2 mM + 0.1 mL tannic acid
# 2.5 mM (+1 mL K2CO3 150 mM) at 70 C, then 1 mL HAuCl4 25 mM
V0 = 152.1
PI_AU = 25 * 1.0 / V0
PI_SC = 2.2 * 150 / V0
PI_TA = 2.5 * 0.1 / V0
PI_K2CO3 = 150 * 1.0 / V0


def piella_seed(T: float = 70.0, ta: float = PI_TA, base: float = PI_K2CO3, pH: float | None = None) -> dict:
    cond = {"temperature_C": T, "time_min": 5.0}
    if pH is not None:
        cond["pH"] = pH
    reag = [rg(AU, "precursor", PI_AU), rg("trisodium citrate", "reductant", PI_SC),
            rg("tannic acid", "capping", ta)]
    if base:
        reag.append(rg("K2CO3", "base", base))
    return {"material": "Au", "method": "citrate reduction", "conditions": cond, "reagents": reag}


def piella_growth(k: int, seed_d: float, seed_cv: float) -> dict:
    if k == 0:
        return piella_seed()
    # each cycle: remove 55 of 152 mL, add 55 mL citrate, inject 2 x 12.5 umol Au
    f = 152.0 / 97.0
    ratio = sum(f ** j for j in range(1, k + 1))   # added Au / seed Au per particle
    cond = {"temperature_C": 70.0, "conc_seed_mM": PI_AU, "conc_precursor_mM": PI_AU * ratio,
            "seed_d_nm": seed_d, "seed_cv_pct": seed_cv, "n_injections": 2 * k,
            "injection_interval_min": 10.0, "time_min": 20.0 * k}
    return {"material": "Au", "method": "seeded growth", "conditions": cond,
            "reagents": [rg("trisodium citrate", "reductant", 2.2)]}


def _li_conc(v: float, **_: Any) -> dict:      # Li et al. 2011, Nanoscale Res. Lett. 6, 440
    return {"material": "Au", "method": "citrate reduction",
            "conditions": {"temperature_C": 100.0, "time_min": 15.0},
            "reagents": [rg(AU, "precursor", v), rg("trisodium citrate", "reductant", 4 * v)]}


def _li_naoh(v: float, **_: Any) -> dict:
    return {"material": "Au", "method": "citrate reduction",
            "conditions": {"temperature_C": 100.0, "time_min": 2.0, "conc_base_mM": v},
            "reagents": [rg(AU, "precursor", 2.5), rg("trisodium citrate", "reductant", 5.0), rg("NaOH", "base", v)]}


def _laspina_ta(v: float, **_: Any) -> dict:   # La Spina et al. 2020 (Ag, tannic acid)
    reag = [rg(AG, "precursor", 0.55), rg("trisodium citrate", "reductant", 1.4)]
    if v > 0:
        reag.append(rg("tannic acid", "capping", v))
    return {"material": "Ag", "method": "citrate reduction",
            "conditions": {"temperature_C": 97.0, "time_min": 40.0}, "reagents": reag}


def _dong_temp(v: float, **_: Any) -> dict:    # Dong et al. 2020 (temperature series)
    return {"material": "Au", "method": "citrate reduction",
            "conditions": {"temperature_C": v, "time_min": 30.0},
            "reagents": [rg(AU, "precursor", 0.25), rg("trisodium citrate", "reductant", 0.625)]}


def _piella_growth(v: float, seed: tuple[float, float] = (1.0, 1.0), **_: Any) -> dict:
    return piella_growth(int(round(v)), *seed)


TRANSLATIONS: dict[str, Callable[..., dict]] = {
    "np-au-li-conc": _li_conc,
    "np-au-li-naoh": _li_naoh,
    "np-ag-laspina-ta": _laspina_ta,
    "np-au-dong-temp": _dong_temp,
    "np-au-piella-ph": lambda v, **_: piella_seed(T=100.0, base=0.0, pH=v),
    "np-au-piella-ta": lambda v, **_: piella_seed(T=100.0, ta=v),
    "np-au-piella-growth": _piella_growth,
}
# cases whose points need the seed particles simulated first (seed size, CV)
NEEDS_SEED = {"np-au-piella-growth": piella_seed}


def generic(card: dict, point: dict) -> dict:
    reag = [{"role": r.get("role", "other"), "name": r.get("name", ""), "conc_mM": r.get("conc_mM")}
            for r in point.get("reagents") or [] if r.get("conc_mM") is not None]
    return {"material": card.get("material", "Au"), "method": card.get("method", ""),
            "conditions": dict(point.get("conditions") or {}), "reagents": reag}


def recipe(card: dict, point: dict, seed: tuple[float, float] | None = None) -> tuple[dict, str]:
    """-> (simulator params, 'paper methods' | 'generic')."""
    fn = TRANSLATIONS.get(card.get("case_id", ""))
    if fn is None:
        return generic(card, point), "generic"
    return fn(float(point["value"]), seed=seed or (1.0, 1.0)), "paper methods"
