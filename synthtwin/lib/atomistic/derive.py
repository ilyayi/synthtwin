"""Derive the simulator physics parameters from literature + the MD summaries.

Run ``python -m synthtwin.lib.atomistic.derive`` after ``md.py --stage analyze``;
it writes ``data/derived_params.json``, which ``params.py`` reads. Every number
carries an uncertainty (1 sigma, or a 16-84 % range where stated) and the list
of sources it came from. numpy only.

Chain of reasoning, per parameter:

gamma_J_m2  metal/solution interfacial energy at 300-373 K
    = gamma_sv(0 K, literature mean of experiment + RPA + SCAN+rVV10)
      + dT (entropy, -0.03 +- 0.03; Tyson-Miller 0 K vs Buffat-Borel at Tm)
      - W_adh(water) (Young-Dupre, 0.10 +- 0.04)
      - Gibbs adsorption term Gamma_max R T ln(1 + K c)  (per capping agent)
    times the MD size factor gamma(d)/gamma_inf (EAM clusters: 1.00-1.03 for
    d >= 2 nm, i.e. no size correction). For Ag the result is combined
    (inverse variance) with the in-water Kelvin value of Ma et al. 2012.
coalescence_dmax_nm
    MD dimers (vacuum, EAM) give the time t_L(d, T) for the elongation xi to
    drop through levels L. Herring's scaling law says t_L ~ d^n for a single
    mechanism (n = 4 surface diffusion, 3 volume diffusion, 1 viscous flow);
    n is fitted per (material, T). The size at which full rounding (xi <= 0.2)
    takes as long as a Brownian collision interval (1 ms .. 1 s) is dmax. A
    melting-point (Pawlow) bound gives the size below which clusters are
    liquid at the synthesis temperature (certain coalescence).
coalescence_eff
    1 / W (Fuchs stability ratio) for two bare, charged clusters (DLVO, linear
    superposition double layer + sphere-sphere Hamaker), Monte-Carlo over
    Hamaker constant, surface potential, ionic strength and size.
capping_dG_eV, ligand_shell_nm
    literature-bounded judgement (see CAPPING below).
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np

from . import literature as L

DATA = Path(__file__).resolve().parent / "data"
KB_EV = 8.617333e-5
KB = 1.380649e-23
R = 8.314462
E0 = 8.8541878e-12
QE = 1.602177e-19
NA = 6.02214e23
T_SYN = 348.0  # K, middle of the 300-373 K synthesis window
MATERIALS = ("Au", "Ag")
CAPPINGS = ("none", "citrate", "tannic", "pvp", "ctab")


def _q(v, u):
    return {"value": float(v), "unc": float(u)}


# ------------------------------------------------------------ capping agents
# dG: Langmuir adsorption free energy in water (simulator convention
# K = exp(-dG/kT) / 1 M; PVP per repeat unit). Gamma_max (mol/m2) and the
# reference bulk concentration c_ref (M) feed the Gibbs adsorption term.
CAPPING = {
    "none": {
        "grade_dG": "strong", "grade_shell": "weak",
        "dG": {"Au": (0.0, 0.0), "Ag": (0.0, 0.0)}, "shell": {"Au": (0.3, 0.2), "Ag": (0.3, 0.2)},
        "Gmax": 0.0, "c_ref": 0.0,
        "src_dG": "no capping agent",
        "src_shell": "hydration/counter-ion layer, judgement",
    },
    "citrate": {
        "grade_dG": "moderate", "grade_shell": "moderate",
        "dG": {"Au": (-0.35, 0.08), "Ag": (-0.40, 0.10)},
        "shell": {"Au": (1.5, 0.7), "Ag": (1.4, 0.7)},
        "Gmax": 3.0e-6, "c_ref": 1.0e-3,
        "src_dG": ("bounded above in strength by the thiolate isotherm free energies on Au (Dinkel 2016 "
                   "-0.48 eV, Dinkel 2018 -0.41 eV on 5 nm NPs): carboxylate binds more weakly than thiolate "
                   "and is displaced by thiols; Ag stronger than Au by the DFT O/halide binding offset "
                   "(OH, Cl: Ag - Au = -0.6..-0.7 eV in vacuum, scaled down for solvation): judgement"),
        "lit_dG": ["dinkel16_MPS_Au_dG", "dinkel18_MPS_Au5nm_dG", "zhang25_OH_Au111_pbe", "zhang25_OH_Ag111_pbe",
                   "goss15_Cl_Au111", "goss15_Cl_Ag111", "santiago14_HCOO_Au111_rpbe"],
        "src_shell": "dense layer ~1.0 nm (Park & Shumaker-Parry 2014) to solvated shell ~2 nm (Cardenas Lopez 2022)",
        "lit_shell": ["parkshumaker14_citrate_Au", "cardenas22_citrate_Au", "cardenas22_citrate_Ag"],
    },
    "tannic": {
        "grade_dG": "weak", "grade_shell": "weak",
        "dG": {"Au": (-0.6, 0.2), "Ag": (-0.6, 0.2)},
        "shell": {"Au": (2.0, 1.0), "Ag": (2.0, 1.0)},
        "Gmax": 4.0e-7, "c_ref": 5.0e-5,
        "src_dG": ("per molecule: multidentate galloyl/phenol binding; single phenol/benzene on Au(111)/Ag(111) "
                   "-0.64..-0.97 eV in vacuum with vdW-DFT, reduced by water displacement; weak"),
        "lit_dG": ["pekoz16_phenol_Au111_revpbevdw", "pekoz16_phenol_Au111_vdwdf2", "carrasco14_benzene_Au111_exp",
                   "carrasco14_benzene_Ag111_exp"],
        "src_shell": "TA molecule ~2 nm; 3.0 nm vendor hydrodynamic shell is an upper bound",
        "lit_shell": ["nanocomposix_TA_Au10"],
    },
    "pvp": {
        "grade_dG": "weak", "grade_shell": "weak",
        "dG": {"Au": (-0.25, 0.15), "Ag": (-0.25, 0.15)},
        "shell": {"Au": (2.5, 1.0), "Ag": (2.5, 1.0)},
        "Gmax": 5.0e-6, "c_ref": 1.0e-3,
        "src_dG": ("per repeat unit (carbonyl O-metal + vdW, weak per unit, strong per chain); "
                   "Ag(100) > Ag(111) qualitatively (Al-Saidi 2012); judgement, weak"),
        "lit_dG": ["alsaidi12_PVP_Ag"],
        "src_shell": "adsorbed PVP loops/tails, judgement (2-4 nm for 10-55 kDa PVP)",
        "lit_shell": [],
    },
    "ctab": {
        "grade_dG": "weak", "grade_shell": "moderate",
        "dG": {"Au": (-0.45, 0.15), "Ag": (-0.45, 0.15)},
        "shell": {"Au": (3.2, 0.5), "Ag": (3.2, 0.5)},
        "Gmax": 3.0e-6, "c_ref": 1.0e-3,
        "src_dG": ("Br- headgroup layer: vacuum DFT Br on Au(111) -0.99 eV, Ag(111) -1.54 eV (vs 1/2 Br2), "
                   "strongly reduced by hydration; bilayer cooperativity; judgement, weak"),
        "lit_dG": ["goss15_Br_Au111", "goss15_Br_Ag111"],
        "src_shell": "CTAB bilayer (Gomez-Grana 2012)",
        "lit_shell": ["gomezgrana12_CTAB_bilayer_Au"],
    },
}


# ------------------------------------------------------------------- gamma
GAMMA_LIT = {"Au": ["tysonmiller77_Au_avg", "patra17_rpa_Au_avg", "patra17_scanrvv10_Au_avg"],
             "Ag": ["tysonmiller77_Ag_avg", "patra17_rpa_Ag_avg", "patra17_scanrvv10_Ag_avg"]}
DT_CORR = (-0.03, 0.03)     # 0 K -> 300-373 K (TM77 0 K 1.50 vs Buffat-Borel 1.38 at Tm for Au)
WATER_CORR = (-0.10, 0.04)  # -W_adh, Young-Dupre 0.072 (1 + cos theta), theta 0-60 deg (Smith 1980)


def _read_csv(name):
    f = DATA / name
    if not f.exists():
        return []
    with f.open() as fh:
        return list(csv.DictReader(fh))


def md_size_factor(material: str) -> dict:
    """gamma_eff(d)/gamma_inf from the EAM clusters (d >= 2 nm) and the
    sphere/(111) ratio."""
    rows = [r for r in _read_csv("md_clusters.csv") if r["material"] == material]
    if not rows:
        return {"factor": _q(1.0, 0.03), "n": 0}
    ginf = float(rows[0]["gamma_inf_fit_J_m2"])
    f = [float(r["gamma_GT_J_m2"]) / ginf for r in rows if float(r["d_nominal_nm"]) >= 2.0]
    bulk = json.loads((DATA / "md_bulk_slab.json").read_text())[material]
    return {"factor": _q(float(np.mean(f)), max(0.02, float(np.ptp(f)))), "n": len(rows),
            "gamma_inf_EAM": ginf, "gamma111_EAM": bulk["gamma_111_J_m2"],
            "sphere_over_111": ginf / bulk["gamma_111_J_m2"]}


def gibbs_adsorption(capping: str, material: str, T: float = T_SYN) -> tuple[float, float]:
    """Szyszkowski/Gibbs lowering of gamma: Gamma_max R T ln(1 + K c)."""
    c = CAPPING[capping]
    if c["Gmax"] <= 0:
        return 0.0, 0.0
    dG, _ = c["dG"][material]
    K = math.exp(-dG / (KB_EV * T))  # 1/M
    v = c["Gmax"] * R * T * math.log1p(K * c["c_ref"])
    return -v, 0.5 * v


def gamma(material: str, capping: str) -> dict:
    g0, u0 = L.combine(GAMMA_LIT[material])
    sf = md_size_factor(material)["factor"]
    dl, ul = gibbs_adsorption(capping, material)
    v = (g0 + DT_CORR[0] + WATER_CORR[0]) * sf["value"]
    u = math.sqrt(u0 ** 2 + DT_CORR[1] ** 2 + WATER_CORR[1] ** 2 + (g0 * sf["unc"]) ** 2)
    src = [L.cite(i) for i in GAMMA_LIT[material]] + [
        "T correction: " + L.cite("buffatborel76_Au_solid_gamma_Tm"),
        "water: Young-Dupre with " + L.cite("smith80_water_clean_Au"),
        "size: EAM cluster MD (this work), gamma(d)/gamma_inf = %.3f" % sf["value"]]
    if material == "Ag":  # combine with the in-water Kelvin fit (inverse variance)
        e = L.by_id("ma12_Ag_kelvin_solution")
        w1, w2 = 1 / u ** 2, 1 / e["uncertainty"] ** 2
        v = (v * w1 + e["value"] * w2) / (w1 + w2)
        u = math.sqrt(1 / (w1 + w2))
        src.append("combined (inverse variance) with " + L.cite("ma12_Ag_kelvin_solution"))
    v += dl
    u = math.sqrt(u ** 2 + ul ** 2)
    if dl:
        src.append(f"Gibbs adsorption of {capping}: {dl:+.3f} J/m2 (Gamma_max R T ln(1+Kc), "
                   f"Gamma_max={CAPPING[capping]['Gmax']:.1e} mol/m2, c={CAPPING[capping]['c_ref']:.0e} M)")
    return {"value": round(v, 3), "unc": round(u, 3), "sources": src,
            "parts": {"lit_vacuum_0K": [round(g0, 3), round(u0, 3)], "dT": DT_CORR, "water": WATER_CORR,
                      "md_size_factor": [round(sf["value"], 4), round(sf["unc"], 4)], "ligand": round(dl, 4)}}


# ----------------------------------------------------------------- melting
def pawlow(material: str, dmin: float = 2.0) -> dict | None:
    """Tm(d) = Tm_b (1 - alpha/d) fitted to the MD melting points (d >= dmin)."""
    rows = [r for r in _read_csv("md_melting.csv") if r["material"] == material and r["Tm_K"]]
    pts = [(float(r["d_eq_nm"]), float(r["Tm_K"])) for r in rows if float(r["d_nominal_nm"]) >= dmin]
    if len(pts) < 3:
        return None
    d, T = np.array(pts).T
    A = np.vstack([np.ones_like(d), -1 / d]).T
    (tb, tba), res, *_ = np.linalg.lstsq(A, T, rcond=None)
    alpha = tba / tb
    resid = T - A @ np.array([tb, tba])
    s = math.sqrt(float(resid @ resid) / max(1, len(d) - 2))
    cov = s ** 2 * np.linalg.inv(A.T @ A)
    # liquid below d* where Tm(d*) = T_SYN
    dstar = alpha / (1 - T_SYN / tb)
    return {"Tm_bulk_K": round(float(tb), 1), "Tm_bulk_unc": round(float(math.sqrt(cov[0, 0])), 1),
            "alpha_nm": round(float(alpha), 3), "rms_K": round(s, 1), "n": len(d),
            "d_liquid_at_348K_nm": round(float(dstar), 2),
            "points": [[round(a, 3), b] for a, b in pts]}


def pawlow_experiment() -> dict:
    """Buffat & Borel Au: bulk 1337 K, ~600 K at 2 nm -> alpha."""
    tb, t2 = 1337.0, L.by_id("buffatborel76_Au_Tm_2nm")["value"]
    alpha = 2.0 * (1 - t2 / tb)
    return {"alpha_nm": round(alpha, 3), "d_liquid_at_348K_nm": round(alpha / (1 - T_SYN / tb), 2)}


# -------------------------------------------------------------- coalescence
XI_DONE = 0.2   # "coalesced": elongation within 20 % of the touching-sphere value of a compact particle


def _win(t, xi, t0, t1):
    m = (t >= t0) & (t <= t1)
    return float(np.mean(xi[m])) if m.any() else float("nan")


def coalescence_runs(start: str = "as-cut") -> list[dict]:
    """Per run: final elongation, completion within the run, and the slow-phase
    relaxation rate r = -dxi/dt between the first quarter and the end of the
    run (100 ps windows). After the neck has formed (first ~20-50 ps) the
    relaxation is diffusive; t_done = t_run + (xi_end - 0.2)/r is a linear
    extrapolation of the slow phase to xi = 0.2 (a lower bound on the true
    time, since the rate keeps falling; inf when r <= noise)."""
    rows = _read_csv("md_coalescence.csv")
    ser_f = DATA / "md_coalescence_series.json"
    if not rows or not ser_f.exists():
        return []
    series = json.loads(ser_f.read_text())
    kind = "coal" if start == "as-cut" else "coalA"
    out = []
    for r in rows:
        if r["start"] != start:
            continue
        d = float(r["d_nm"])
        s = series.get(f"{kind}_{r['material']}_{d:g}_{r['T_K']}_{r['rep']}")
        if s is None:
            continue
        t, xi = np.asarray(s["t_ps"]), np.asarray(s["xi"])
        te = float(t[-1])
        t1 = 0.25 * te
        x1, x2 = _win(t, xi, t1 - 50, t1 + 50), _win(t, xi, te - 100, te)
        noise = float(np.std(xi[t > te - 200])) if (t > te - 200).sum() > 3 else 0.02
        rate = (x1 - x2) / (te - 50 - t1)
        done = r["tau80_ps"] not in ("", None)
        if done:
            t_done = float(r["tau80_ps"])
        elif rate > 0 and (x1 - x2) > max(noise, 0.01):
            t_done = te + (x2 - XI_DONE) / rate
        else:
            t_done = math.inf
        out.append({"material": r["material"], "T_K": int(r["T_K"]), "d_nm": d, "rep": r["rep"],
                    "xi_end": round(x2, 3), "rate_per_ns": round(rate * 1e3, 4), "done": done,
                    "t_done_ps": t_done, "t_run_ps": te})
    return out


def coalescence_scaling(start: str = "as-cut") -> dict:
    """Per (material, T): completion fraction and mean final xi per size, and a
    power-law fit t_done = t1 (d / 1.5 nm)^n through the per-size geometric
    means of the extrapolated completion times (sizes with any infinite
    replicate are excluded from the fit and reported as 'stalled'). With
    Herring's scaling a single sintering mechanism gives n = 4 (surface
    diffusion); n >> 4 means the mechanism changes with size (faceting,
    nucleation-limited layer motion). Bootstrap over replicates -> n range."""
    runs = coalescence_runs(start)
    out = {}
    rng = np.random.default_rng(0)
    for m in MATERIALS:
        for T in sorted({x["T_K"] for x in runs if x["material"] == m}):
            sub = [x for x in runs if x["material"] == m and x["T_K"] == T]
            ds = sorted({x["d_nm"] for x in sub})
            res = {"sizes_nm": ds, "n_runs": len(sub),
                   "complete_frac": {f"{d:g}": round(float(np.mean([x["done"] for x in sub if x["d_nm"] == d])), 2) for d in ds},
                   "xi_end_mean": {f"{d:g}": round(float(np.mean([x["xi_end"] for x in sub if x["d_nm"] == d])), 3) for d in ds},
                   "xi_end_sd": {f"{d:g}": round(float(np.std([x["xi_end"] for x in sub if x["d_nm"] == d])), 3) for d in ds},
                   "t_done_ns": {f"{d:g}": _gm([x["t_done_ps"] for x in sub if x["d_nm"] == d]) for d in ds}}
            res["stalled_sizes_nm"] = [d for d in ds if res["t_done_ns"][f"{d:g}"] is None]
            fit = _powerfit(sub)
            if fit:
                res.update(fit)
                boots = []
                for _ in range(300):
                    pick = [sub[i] for i in rng.integers(0, len(sub), len(sub))]
                    f = _powerfit(pick)
                    if f:
                        boots.append(f["n"])
                if len(boots) > 20:
                    res["n_boot16_84"] = [round(float(np.percentile(boots, 16)), 2), round(float(np.percentile(boots, 84)), 2)]
            out[f"{m}_{T}"] = res
    return out


def _gm(v):
    v = [x for x in v]
    if not v or any(not math.isfinite(x) for x in v):
        return None  # stalled: at least one replicate shows no measurable slow-phase relaxation
    return round(float(np.exp(np.mean(np.log(v)))) * 1e-3, 3)


def _powerfit(sub):
    ds = sorted({x["d_nm"] for x in sub})
    pts = []
    for d in ds:
        v = [x["t_done_ps"] for x in sub if x["d_nm"] == d]
        if v and all(math.isfinite(x) and x > 0 for x in v):
            pts.append((d, float(np.mean(np.log(v)))))
    if len(pts) < 2:
        return None
    x = np.log(np.array([p[0] for p in pts]) / 1.5)
    y = np.array([p[1] for p in pts])
    n, c = np.polyfit(x, y, 1)
    # any stalled size must be at least as slow as the fit predicts there
    return {"n": round(float(n), 2), "t1_ps": round(float(math.exp(c)), 1), "fit_sizes_nm": [p[0] for p in pts]}


def dmax_from_scaling(fit: dict, tau_coll_s: float, n_min: float = 4.0) -> float | None:
    """Size whose extrapolated completion time equals tau_coll, with the
    fitted exponent (floored at Herring's n = 4)."""
    if not fit or "n" not in fit:
        return None
    n = max(n_min, fit["n"])
    return 1.5 * (tau_coll_s / (fit["t1_ps"] * 1e-12)) ** (1.0 / n)


def brownian_tau(N_m3: float, T: float = T_SYN, eta: float = 4.0e-4) -> float:
    """Collision interval 1/(beta N), beta = 8kT/(3 eta) (size-independent
    continuum kernel for equal spheres); eta of water at ~75 C."""
    return 1.0 / (8 * KB * T / (3 * eta) * N_m3)


# -------------------------------------------------------- collision efficiency
def fuchs_W(a, A, psi, I_M, T=T_SYN, eps_r=65.0):
    """Fuchs stability ratio for equal spheres of radius a (m): W = 2a int_{2a}^inf
    exp(V/kT) dr / r^2 with V = vdW (Hamaker, full sphere-sphere) + double
    layer (linear superposition, LSA: 4 pi eps a^2 psi^2 exp(-kappa h)/r)."""
    kT = KB * T
    kappa = math.sqrt(2 * NA * 1000 * I_M * QE ** 2 / (eps_r * E0 * kT))
    h = np.geomspace(0.15e-9, 200e-9, 4000)  # stop at ~1.5 A (atomic contact)
    r = 2 * a + h
    x = r ** 2
    vdw = -A / 6 * (2 * a * a / (x - 4 * a * a) + 2 * a * a / x + np.log((x - 4 * a * a) / x))
    edl = 4 * math.pi * eps_r * E0 * a * a * psi ** 2 * np.exp(-kappa * h) / r
    V = (vdw + edl) / kT
    f = np.exp(np.clip(V, -50, 50)) / r ** 2
    return float(2 * a * np.trapezoid(f, r) if hasattr(np, "trapezoid") else 2 * a * np.trapz(f, r)), float(V.max())


def collision_eff(n: int = 400, seed: int = 1) -> dict:
    rng = np.random.default_rng(seed)
    eff, vmax = [], []
    for _ in range(n):
        d = rng.uniform(1.5, 3.0) * 1e-9
        A = rng.uniform(1.5e-19, 3.5e-19)
        psi = -rng.uniform(0.015, 0.045)
        I = 10 ** rng.uniform(-3, -2)
        W, vm = fuchs_W(d / 2, A, psi, I)
        eff.append(1 / W)
        vmax.append(vm)
    eff = np.array(eff)
    return {"median": round(float(np.median(eff)), 3), "p16": round(float(np.percentile(eff, 16)), 3),
            "p84": round(float(np.percentile(eff, 84)), 3), "Vmax_kT_median": round(float(np.median(vmax)), 2),
            "ranges": {"d_nm": [1.5, 3.0], "A_J": [1.5e-19, 3.5e-19], "psi_mV": [-45, -15], "I_M": [1e-3, 1e-2],
                       "T_K": T_SYN}}


# --------------------------------------------------------------------- all
TAU_COLL_S = (1e-3, 1.0)  # N ~ 1e17..1e20 m^-3 nuclei/clusters during nucleation-growth


HYDRO = (0.75, 0.25)  # hydrodynamic retardation of the collision rate (factor 0.5-1 for nm spheres)


def recommend(out: dict) -> dict:
    """Final per-material choices for coalescence_dmax_nm / coalescence_eff."""
    eff = out["coalescence_eff_dlvo"]
    e_v = min(1.0, eff["median"]) * HYDRO[0]
    e_u = math.hypot(HYDRO[1], 0.5 * (min(1.0, eff["p84"]) - eff["p16"]))
    rec = {}
    for m in MATERIALS:
        md = out["materials"][m]["md"]
        pw = md.get("pawlow") or {}
        rec[m] = {
            "coalescence_eff": {
                "value": round(e_v, 2), "unc": round(min(e_u, e_v), 2), "grade": "moderate",
                "sources": [f"DLVO + Fuchs stability ratio for bare charged 1.5-3 nm clusters (this work): "
                            f"1/W median {eff['median']} (16-84 %: {eff['p16']}-{eff['p84']}), max barrier "
                            f"{eff['Vmax_kT_median']} kT -> no electrostatic barrier at this size; x {HYDRO[0]} for "
                            "hydrodynamic retardation; MD (vacuum) shows sticking on every contact",
                            L.cite("israelachvili11_hamaker_metals")]},
            "coalescence_dmax_nm": _dmax_choice(m, md, pw, out),
        }
    return rec


DMAX = {"Au": (3.0, 1.5), "Ag": (2.5, 1.5)}


def _dmax_choice(m, md, pw, out):
    """Bracket: certain coalescence (liquid-like at 348 K, or rounding within
    ns in MD) <= dmax <= rounding on the s-min growth timescale (faceted
    particles, in-situ TEM). The continuum d^4 law would allow tens of nm and
    is rejected by the MD stall of necked dimers from 2 nm up."""
    sc = out["coalescence_scaling_as_cut"]
    lines = []
    for T in (300, 373):
        r = sc.get(f"{m}_{T}")
        if r:
            lines.append(f"MD {T} K: fraction of dimers fully rounded (xi<=0.2) in 2 ns by size "
                         + ", ".join(f"{k} nm: {v}" for k, v in r["complete_frac"].items())
                         + "; mean final xi " + ", ".join(f"{k}: {v}" for k, v in r["xi_end_mean"].items()))
    v, u = DMAX[m]
    src = [f"liquid-like below {pw.get('d_liquid_at_348K_nm')} nm at 348 K (Pawlow fit to EAM melting points, this work)"
           + (f"; {out['pawlow_experiment_Au']['d_liquid_at_348K_nm']} nm from Buffat & Borel 1976" if m == "Au" else "")]
    src += lines
    src += ["necks form on every contact at all sizes 1.5-8 nm (irreversible, dPE < 0), but shape relaxation stalls more "
            "with size (Au residual xi after 2 ns ~0.3 at 1.5 nm, ~0.45 at 2-2.5 nm, ~0.6 at 3 nm, ~0.75 at 4-5 nm, "
            "~0.85 at 6-8 nm; Ag higher at each size) and depends only weakly on T from 3 nm up: faceted, "
            "nucleation-limited regime",
            L.cite("lim09_Au_deca_coalescence"),
            L.cite("magdassi10_Ag_RT_sintering"),
            "judgement: dmax between the certain (~1.5 nm) and the s-min (~5 nm) rounding sizes; Ag set 0.5 nm below "
            "Au because Ag dimers round more slowly in MD (Ag at d behaves like Au at d + 1 nm), but not lower because "
            "destabilised Ag particles coalesce quickly at room temperature in experiments"]
    return {"value": v, "unc": u, "grade": "weak", "sources": src}


def derive_all() -> dict:
    out = {"T_synthesis_K": T_SYN, "materials": {}, "capping": {}}
    scal = coalescence_scaling("as-cut")
    scalA = coalescence_scaling("annealed")
    eff = collision_eff()
    out["coalescence_eff_dlvo"] = eff
    out["coalescence_scaling_as_cut"] = scal
    out["coalescence_scaling_annealed"] = scalA
    out["tau_coll_s_range"] = list(TAU_COLL_S)
    out["pawlow_experiment_Au"] = pawlow_experiment()
    for m in MATERIALS:
        md = {"size_factor": md_size_factor(m), "pawlow": pawlow(m)}
        dm = {}
        for T in (300, 373):
            f = scal.get(f"{m}_{T}")
            if f and "n" in f:
                dm[str(T)] = [dmax_from_scaling(f, TAU_COLL_S[0]), dmax_from_scaling(f, TAU_COLL_S[1])]
        md["dmax_herring_nm"] = dm
        out["materials"][m] = {"md": md, "Vm_m3_mol": _q(L.by_id(f"crc_{m}_Vm")["value"], L.by_id(f"crc_{m}_Vm")["uncertainty"]),
                               "gamma": {c: gamma(m, c) for c in CAPPINGS}}
    for c in CAPPINGS:
        out["capping"][c] = {k: v for k, v in CAPPING[c].items() if k not in ("dG", "shell")}
        out["capping"][c]["dG"] = {m: list(CAPPING[c]["dG"][m]) for m in MATERIALS}
        out["capping"][c]["shell"] = {m: list(CAPPING[c]["shell"][m]) for m in MATERIALS}
    out["recommended"] = recommend(out)
    return out


def main():
    out = derive_all()
    out.update(json.loads((DATA / "derived_choices.json").read_text()) if (DATA / "derived_choices.json").exists() else {})
    (DATA / "derived_params.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps({m: {c: (g["value"], g["unc"]) for c, g in out["materials"][m]["gamma"].items()}
                      for m in MATERIALS}, indent=1))
    print(json.dumps(out["coalescence_eff_dlvo"], indent=1))
    for m in MATERIALS:
        print(m, json.dumps(out["materials"][m]["md"], default=float)[:1500])
    print(json.dumps(out["coalescence_scaling_as_cut"], indent=1)[:4000])


if __name__ == "__main__":
    main()
