"""Does the atomistic parameter set help the simulator?

    python -m synthtwin.lib.atomistic.helps      (needs synthtwin.lib.np)

Runs the simulator's qualitative literature checks (Turkevich citrate:Au
ratio, NaBH4 Au/Ag, tannic acid Au, Lee-Meisel Ag citrate) with
  default    - the simulator's assumed effective parameters
  physical   - physics_overrides(material, capping), as-is
  phys+cal   - physical, with log10_nucleation_scale re-fitted on ONE anchor
               (Au Turkevich ratio 3.5 -> 13 nm), other cases are predictions
  phys+steep - physical gamma with a steeper nucleation law: the simulator's
               nuc_barrier_ref_kT raised 30 -> STEEP_KT with the CNT prefactor
               raised by (STEEP_KT - 30)/ln 10 decades so the onset stays put,
               i.e. a nucleation order d lnJ/d lnS at onset of ~19 instead of
               ~1 (physical gamma) or ~10 (default gamma); + anchor cal
and compares the nominal mean size and CV with approximate literature ranges
(error = |log| distance outside the range, 0 inside; the anchor is excluded
from the size score). The simulator defaults were tuned by hand to these
same trends, so the comparison favours the defaults. Also isolates
each override (gamma alone, coalescence alone, capping alone).
"""
from __future__ import annotations

import json
import math
import sys

from .params import physics_overrides

# (label, material, method, conditions, capping, literature d range nm, CV range %, ref)
# ranges are approximate literature ranges (several reports per recipe), not single data points
CASES = [
    ("Au citrate 1:1", "Au", "citrate", {"ratio_reductant_precursor": 1.0, "conc_precursor_mM": 0.25,
                                          "temperature_C": 100, "time_min": 30}, "citrate", (20, 40), (10, 25), "Frens 1973"),
    ("Au citrate 3.5:1", "Au", "citrate", {"ratio_reductant_precursor": 3.5, "conc_precursor_mM": 0.25,
                                            "temperature_C": 100, "time_min": 30}, "citrate", (12, 16), (8, 15), "Turkevich 1951; Kimling 2006"),
    ("Au citrate 10:1", "Au", "citrate", {"ratio_reductant_precursor": 10.0, "conc_precursor_mM": 0.25,
                                           "temperature_C": 100, "time_min": 30}, "citrate", (10, 20), (8, 20), "Ji 2007"),
    ("Au NaBH4", "Au", "borohydride", {"ratio_reductant_precursor": 4.0, "conc_precursor_mM": 0.25,
                                       "temperature_C": 25, "time_min": 30, "conc_capping_mM": 0.25}, "citrate", (3, 6), (10, 30), "Jana 2001"),
    ("Ag NaBH4", "Ag", "borohydride", {"ratio_reductant_precursor": 2.0, "conc_precursor_mM": 1.0,
                                       "temperature_C": 0, "time_min": 30}, "none", (5, 15), (15, 40), "Creighton 1979; Mulfinger 2007"),
    ("Au tannic 0.01 mM", "Au", "tannic", {"conc_precursor_mM": 0.25, "conc_capping_mM": 0.01,
                                           "ratio_reductant_precursor": 3.5, "temperature_C": 70, "time_min": 30},
     "tannic", (4, 10), (5, 15), "Piella 2016"),
    ("Ag citrate (Lee-Meisel)", "Ag", "citrate", {"ratio_reductant_precursor": 3.5, "conc_precursor_mM": 1.0,
                                                  "temperature_C": 100, "time_min": 60}, "citrate", (40, 80), (20, 50), "Lee & Meisel 1982"),
]
ANCHOR = 1  # index of the calibration anchor (Au citrate 3.5:1)
ANCHOR_D = 13.0
STEEP_KT = 200.0
STEEP = {"nuc_barrier_ref_kT": STEEP_KT, "log10_nuc_prefactor": 30.0 + (STEEP_KT - 30.0) / math.log(10.0)}


def _run(material, method, cond, physics=None, cal=None):
    from synthtwin.lib.np import model
    p = {"material": material, "method": method, "conditions": dict(cond), "reagents": [], "n_draws": 1, "seed": 0}
    if physics:
        p["physics"] = physics
    if cal:
        p["calibration"] = cal
    out = model.predict(p, material)
    return out["size_mean_nm"]["value"], out["size_cv_pct"]["value"]


def _phys(material, capping, keys=None, extra=None):
    p = physics_overrides(material, capping, strip=True)
    p = {k: v for k, v in p.items() if keys is None or k in keys}
    return {**p, **(extra or {})}


def _fit_nuc(keys=None, extra=None):
    lab, m, meth, cond, cap, _, _, _ = CASES[ANCHOR]
    phys = _phys(m, cap, keys, extra)

    def err(x):
        d, _ = _run(m, meth, cond, phys, {"log10_nucleation_scale": x})
        return math.log(max(d, 1e-3) / ANCHOR_D)

    lo, hi = -8.0, 4.0
    elo, ehi = err(lo), err(hi)
    if elo * ehi > 0:
        return lo if abs(elo) < abs(ehi) else hi
    for _ in range(25):  # bisection (size falls with more nucleation)
        mid = 0.5 * (lo + hi)
        e = err(mid)
        if e * elo > 0:
            lo, elo = mid, e
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _score(d, rng):
    lo, hi = rng
    if not d > 0:
        d = 1e-3
    if lo <= d <= hi:
        return 0.0
    return abs(math.log(d / (lo if d < lo else hi)))


def run():
    variants = {
        "default": (None, None, None),
        "gamma only": (["gamma_J_m2"], None, None),
        "coalescence only": (["coalescence_dmax_nm", "coalescence_eff"], None, None),
        "capping+shell only": (["capping_dG_eV", "ligand_shell_nm"], None, None),
        "physical (all six)": ("all", None, None),
        "physical except gamma": (["Vm_m3_mol", "coalescence_dmax_nm", "coalescence_eff", "capping_dG_eV",
                                   "ligand_shell_nm"], None, None),
    }
    cal_all = _fit_nuc(None)
    cal_def = _fit_nuc([])
    cal_steep = _fit_nuc(None, STEEP)
    variants["default + nuc cal"] = (None, cal_def, None)
    variants["physical + nuc cal"] = ("all", cal_all, None)
    variants["physical + steep nuc + nuc cal"] = ("all", cal_steep, STEEP)
    rows = []
    for lab, m, meth, cond, cap, rng, cvr, ref in CASES:
        row = {"case": lab, "lit_nm": list(rng), "lit_cv": list(cvr), "ref": ref}
        for vn, (keys, cal, extra) in variants.items():
            phys = None if keys is None else _phys(m, cap, None if keys == "all" else keys, extra)
            calib = {"log10_nucleation_scale": cal} if cal is not None else None
            try:
                d, cv = _run(m, meth, cond, phys, calib)
            except Exception as exc:  # pragma: no cover - simulator failure is a result too
                d, cv = float("nan"), float("nan")
                row.setdefault("errors", {})[vn] = repr(exc)
            row[vn] = [round(d, 2), round(cv, 1)]
        rows.append(row)
    summ = {}
    for vn in variants:
        sc = [_score(r[vn][0], r["lit_nm"]) for i, r in enumerate(rows) if i != ANCHOR and math.isfinite(r[vn][0])]
        cv = [_score(r[vn][1], r["lit_cv"]) for r in rows if math.isfinite(r[vn][1])]
        summ[vn] = {"size_err": round(sum(sc) / len(sc), 3), "size_in_range": sum(1 for s in sc if s == 0),
                    "n_size": len(sc), "cv_err": round(sum(cv) / len(cv), 3),
                    "cv_in_range": sum(1 for s in cv if s == 0), "n_cv": len(cv)}
    return {"rows": rows, "summary": summ,
            "nuc_cal": {"default": round(cal_def, 2), "physical": round(cal_all, 2), "physical_steep": round(cal_steep, 2)}}


if __name__ == "__main__":
    res = run()
    json.dump(res, sys.stdout, indent=1)
