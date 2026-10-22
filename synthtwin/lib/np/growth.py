"""Nucleation + growth population balance with nucleation cohorts.

simulate(run, draws) integrates one recipe for D parameter draws at once
(numpy arrays of shape (D,) or (D, K)). Chemistry: precursor P is reduced to
monomer M by a homogeneous path, k1(T, reductant, pH) * P, and by an
autocatalytic surface path, k2 * area * P (Finke-Watzky type, deposited
directly on the particles in proportion to their area). Monomer forms nuclei
by classical nucleation theory, J = A exp(-B / ln^2 S) with S = M / Ceq and
B = 16 pi gamma^3 v^2 / (3 (kT)^3); nuclei appear at 1.25 x the critical radius
r* = r_c / ln S (r_c = 2 gamma v / kT). Particles grow by mixed diffusion /
surface-reaction control with a Gibbs-Thomson term,
    dn_atoms/dt = 4 pi r^2 k_eff (M - Ceq exp(r_c / r)),  1/k_eff = 1/k_s + r/D,
and k_s, k2 are slowed by capping coverage theta (Langmuir, chemistry.coverage).
Particles smaller than coalescence_dmax_nm merge on Brownian collision
(kernel 8kT/3eta) with efficiency coalescence_eff * (1 - theta).

Cohorts: slot 0 holds seeds; slot k collects the nuclei born in the k-th
log-spaced time window. Each cohort carries (number, metal amount, log-radius
spread); the spread follows the growth law (size focusing) and coalescence
(mixing of merged and unmerged particles). Monomer uses a backward-Euler step
(stable at large dt); the time step adapts to the nucleation rate. Metal is
conserved exactly by construction; result["mass_balance"] reports it.

Called by model.predict; tests call it directly.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.special import ndtr

from synthtwin.lib.np import chemistry as C
from synthtwin.lib.np import params as P

K_SLOTS = 90
D_GRID_NM = np.geomspace(0.3, 400.0, 181)          # histogram bin edges (nm)
D_CENTERS_NM = np.sqrt(D_GRID_NM[1:] * D_GRID_NM[:-1])
D_MIN_COUNT_NM = 1.0                                # smallest particle counted (TEM)


def _reductant_table(run: C.Run) -> list[dict[str, Any]]:
    """Active reductants with their rate parameters (main one from run.p)."""
    p = run.p
    out = []
    main = next(iter(run.reductants))
    for name, conc in run.reductants.items():
        if name == "citrate_cap" or conc <= 0:
            continue
        if name == main:
            rp = {k[4:]: v for k, v in p.items() if k.startswith("red_")}
        else:
            rp = {k: v for k, (v, _s) in P.REDUCTANTS[name].items()}
        ph_act = C.reductant_activity(rp["ph_model"], run.pH, p["citrate_pKa"])
        metal = (C.au_reactivity(run.pH, p["au_hydrolysis_pK"], p["au_species_reactivity"])
                 if run.material == "Au" else rp.get("Ag_factor", 1.0))
        arr = C.arrhenius(rp["Ea_kJ_mol"], run.T_K, rp["T_ref_C"]) * p.get("rate_scale", 1.0)
        tau = rp["tau_act_s"] / arr if rp["tau_act_s"] else 0.0
        out.append({
            "name": name, "c0": conc,
            "k1": rp["k1"] * arr * ph_act * metal, "k2": rp["k2"] * arr * ph_act * metal,
            "stoich": rp["stoich_Au"] if run.material == "Au" else rp["stoich_Ag"], "tau": tau,
        })
    return out


def simulate(run: C.Run, draws: dict[str, np.ndarray]) -> dict[str, Any]:
    """run + per-draw multipliers -> size distribution, stats, time course."""
    p = run.p
    D = len(draws["nuc"])
    T = run.T_K
    kT = C.KB * T
    eta = C.water_viscosity(T)
    Vm = float(p["Vm_m3_mol"])
    v_at = Vm / C.NA
    gamma = float(p["gamma_J_m2"]) * draws.get("gamma", np.ones(D))
    B = 16.0 * math.pi * gamma ** 3 * v_at ** 2 / (3.0 * kT ** 3)
    lnS_on = np.sqrt(B / p["nuc_barrier_ref_kT"])
    Ceq = p["nuc_onset_mM"] / np.exp(lnS_on)
    rc = 2.0 * gamma * v_at / kT
    A_nuc = 10.0 ** (p["log10_nuc_prefactor"] + draws["nuc"])
    Dm = p["D_monomer_m2_s"] * (T / 298.15) * (C.water_viscosity(298.15) / eta)
    ks0 = (p["k_surface_m_s"] * C.arrhenius(p.get("k_surface_Ea_kJ_mol", 0.0), T, 100.0)
           * draws["ks"] * p.get("growth_scale", 1.0))
    K_coll = 8.0 * kT / (3.0 * eta)
    dmax = float(p["coalescence_dmax_nm"]) * 1e-9
    eff0 = float(p["coalescence_eff"]) * draws["eff"]
    block = p["capping_block"]

    reds = _reductant_table(run)
    c_red = np.array([[r["c0"]] * D for r in reds]).reshape(len(reds), D)
    k1 = np.array([r["k1"] for r in reds])[:, None] * draws["k1"][None, :]
    k2 = np.array([r["k2"] for r in reds])[:, None] * draws["k2"][None, :]
    stoich = np.array([r["stoich"] for r in reds])[:, None]
    taus = np.array([r["tau"] for r in reds])[:, None]
    idx_cit = [i for i, r in enumerate(reds) if r["name"] == "citrate"]
    cit_cap = run.reductants.get("citrate_cap", 0.0)
    a_cit = C.citrate_fractions(run.pH, p["citrate_pKa"])
    cit_charged = float(a_cit[2] + a_cit[3])
    dG = np.asarray(p["capping_dG_eV"]) + draws["dG"]
    K_prim = C.langmuir_K(dG, T)
    K_cit = K_prim if run.capping == "citrate" else C.langmuir_K(
        P.CAPPING["citrate"]["capping_dG_eV"][0] + draws["dG"], T)
    c_prim = 0.0 if run.capping in ("citrate", "none") else run.c_capping

    # state
    dose = run.c_precursor / run.n_injections
    Pc = np.full(D, dose)
    M = np.zeros(D)
    n = np.zeros((D, K_SLOTS))
    mol = np.zeros((D, K_SLOTS))
    sig = np.zeros((D, K_SLOTS))
    if run.seed_d_nm > 0 and run.c_seed > 0:
        r_s = 0.5e-9 * run.seed_d_nm
        n[:, 0] = run.c_seed * Vm / (4.0 / 3.0 * math.pi * r_s ** 3)
        mol[:, 0] = run.c_seed
        sig[:, 0] = run.seed_cv
    total_in = run.c_precursor + run.c_seed
    t_end = run.time_s
    edges = np.geomspace(1e-4, t_end, K_SLOTS - 1)
    inj_times = [run.injection_interval_s * j for j in range(1, run.n_injections)]
    t, dt, injected, steps = 0.0, 1e-6, 1, 0
    course: list[tuple[float, ...]] = []

    while t < t_end - 1e-12 and steps < 20000:
        steps += 1
        nxt = min([x for x in inj_times if x > t + 1e-12] + [t_end])
        dt = min(dt, nxt - t)
        r = np.where(n > 0, np.cbrt(np.maximum(mol, 0) * Vm / (4.0 / 3.0 * math.pi * np.maximum(n, 1e-300))), 0.0)
        cit_free = c_red[idx_cit].sum(axis=0) if idx_cit else np.zeros(D)
        Kc = K_cit * (cit_free + cit_cap) * cit_charged + K_prim * c_prim
        theta = Kc / (1.0 + Kc)
        ks = ks0 * (1.0 - block * theta)
        area_i = 4.0 * math.pi * r ** 2 * n
        area = area_i.sum(axis=1)
        act = 1.0 - np.exp(-(t + run.preheat_s) / np.maximum(taus, 1e-30)) if taus.any() else 1.0
        act = np.where(taus > 0, act, 1.0)
        k_hom_r = k1 * c_red * act                       # (R, D)
        k_sur_r = k2 * c_red * act * (1.0 - block * theta) * area
        k_tot = (k_hom_r + k_sur_r).sum(axis=0)
        keff = np.where(n > 0, 1.0 / (1.0 / ks[:, None] + r / Dm), 0.0)
        a_i = area_i * keff
        b_i = a_i * Ceq[:, None] * np.exp(np.minimum(rc[:, None] / np.maximum(r, 1e-12), 50.0))
        kap, beta = a_i.sum(axis=1), b_i.sum(axis=1)
        while True:   # adapt dt to nucleation and precursor consumption
            frac = 1.0 - np.exp(-k_tot * dt)
            dP = Pc * frac
            share_h = np.where(k_tot > 0, k_hom_r.sum(axis=0) / np.maximum(k_tot, 1e-300), 0.0)
            hom = dP * share_h
            M_pred = (M + hom + beta * dt) / (1.0 + kap * dt)
            J0, J1 = _nuc_rate(M, Ceq, A_nuc, B), _nuc_rate(M_pred, Ceq, A_nuc, B)
            lnS = np.log(np.maximum(np.maximum(M, M_pred) / Ceq, 1.0 + 1e-9))
            r_nuc = np.maximum(1.25 * rc / lnS, 0.15e-9)
            g = 4.0 / 3.0 * math.pi * r_nuc ** 3 / Vm      # mol per nucleus
            dn_nuc = 0.5 * (J0 + J1) * dt
            nuc = dn_nuc * g
            small = (n > 0) & (r < 0.5 * dmax)
            Ns = (n * small).sum(axis=1)
            fcoal = 0.5 * eff0 * (1.0 - theta) * K_coll * Ns * dt
            avail = M + hom
            with np.errstate(over="ignore", divide="ignore"):
                big_jump = (np.abs(np.log((J1 + 1e-300) / (J0 + 1e-300))) > 2.0) & (nuc > 1e-7 * total_in)
            too_much = (nuc > 0.3 * avail + 1e-12 * total_in) | (fcoal > 0.2) | ((frac > 0.3) & (Pc > 1e-6 * total_in))
            if (big_jump.any() or too_much.any()) and dt > 1e-9:
                dt *= 0.5
                continue
            break
        nuc = np.minimum(nuc, 0.5 * avail)
        dn_nuc = nuc / g
        surf = dP - hom
        M_new = (M + hom - nuc + beta * dt) / (1.0 + kap * dt)
        dep = (a_i * M_new[:, None] - b_i) * dt
        dep = np.maximum(dep, -mol)
        dep_s = np.where(area[:, None] > 0, surf[:, None] * area_i / np.maximum(area[:, None], 1e-300), 0.0)
        surf_lost = surf - dep_s.sum(axis=1)                # no particles yet -> monomer
        # dissolution capped by a cohort's metal -> less monomer released than the
        # implicit step assumed; scale growth down so monomer stays >= 0
        deficit = np.maximum(dep.sum(axis=1) - (M + hom - nuc + surf_lost), 0.0)
        pos = np.maximum(dep, 0.0).sum(axis=1)
        keep = np.where(pos > 0, 1.0 - np.minimum(deficit / np.maximum(pos, 1e-300), 1.0), 1.0)
        dep = np.where(dep > 0, dep * keep[:, None], dep)
        # log-radius spread: absolute spread follows d(dr/dt)/dr of the monomer growth law
        C_r = b_i / np.maximum(a_i, 1e-300)
        gprime = Vm * (-(keff ** 2) / Dm * (M_new[:, None] - C_r)
                       + keff * C_r * rc[:, None] / np.maximum(r, 1e-12) ** 2)
        mol_new = mol + dep + dep_s
        r_new = np.where(n > 0, np.cbrt(np.maximum(mol_new, 0) * Vm / (4.0 / 3.0 * math.pi * np.maximum(n, 1e-300))), 0.0)
        sig = np.where(r_new > 0, sig * r / np.maximum(r_new, 1e-300) * np.exp(np.clip(gprime * dt, -2, 1)), sig)
        sig = np.minimum(sig, 0.8)
        mol = mol_new
        M = np.maximum(M + hom - nuc - dep.sum(axis=1) + surf_lost, 0.0)
        Pc = Pc - dP
        for i, red in enumerate(reds):  # reductant consumption (by its share of reduction)
            share = (k_hom_r[i] + k_sur_r[i]) / np.maximum(k_tot, 1e-300)
            c_red[i] = np.maximum(c_red[i] - stoich[i, 0] * dP * share, 0.0)
        # coalescence of small particles (volume kept in the cohort)
        if fcoal.max() > 0:
            f = np.where(small, np.minimum(fcoal, 0.45)[:, None], 0.0)
            pm = f / (1.0 - f)
            s_c2 = float(p.get("coalescence_sigma", 0.2)) ** 2   # self-preserving spread (assumed)
            sig = np.sqrt(sig ** 2 + pm * np.maximum(s_c2 - sig ** 2, 0.0))
            n = n * (1.0 - f)
        # new nuclei into the current time slot (mixture of log-radius)
        k = min(1 + int(np.searchsorted(edges, t)), K_SLOTS - 1)
        add = dn_nuc > 0
        if add.any():
            n_old, m_old = n[:, k], mol[:, k]
            r_old = np.where(n_old > 0, np.cbrt(np.maximum(m_old, 0) * Vm / (4.0 / 3.0 * math.pi * np.maximum(n_old, 1e-300))), r_nuc)
            n_tot = n_old + dn_nuc
            w = dn_nuc / np.maximum(n_tot, 1e-300)
            lr_old, lr_new = np.log(np.maximum(r_old, 1e-12)), np.log(r_nuc)
            mean = (1 - w) * lr_old + w * lr_new
            var = (1 - w) * (sig[:, k] ** 2 + (lr_old - mean) ** 2) + w * (lr_new - mean) ** 2
            sig[:, k] = np.where(add, np.sqrt(var), sig[:, k])
            n[:, k] = n_tot
            mol[:, k] = m_old + nuc
        # dissolve cohorts that shrank to nothing
        gone = (n > 0) & ((mol <= 1e-30 * total_in) | (_radii(n, mol, Vm) < 0.1e-9))
        if gone.any():
            M = M + np.where(gone, mol, 0.0).sum(axis=1)
            n, mol, sig = np.where(gone, 0.0, n), np.where(gone, 0.0, mol), np.where(gone, 0.0, sig)
        t += dt
        if injected < run.n_injections and t >= run.injection_interval_s * injected - 1e-9:
            Pc = Pc + dose
            injected += 1
        if steps % 5 == 0 or t >= t_end - 1e-12:
            course.append(_course_row(t, Pc, M, n, mol, Vm))
        dt = min(dt * 1.25, 0.05 * t + 1e-6, 0.02 * t_end)
    return _result(run, n, mol, sig, Pc, M, total_in, course, steps, draws, Vm)


def _nuc_rate(M, Ceq, A, B):
    S = M / Ceq
    lnS = np.log(np.maximum(S, 1.0 + 1e-12))
    return np.where(S > 1.0, A * np.exp(-np.minimum(B / lnS ** 2, 700.0)), 0.0)


def _radii(n, mol, Vm):
    return np.where(n > 0, np.cbrt(np.maximum(mol, 0) * Vm / (4.0 / 3.0 * math.pi * np.maximum(n, 1e-300))), 0.0)


def _course_row(t, Pc, M, n, mol, Vm):
    d = 2e9 * _radii(n[:1], mol[:1], Vm)[0]
    keep = d >= D_MIN_COUNT_NM
    N = n[0][keep].sum()
    mean_d = float((n[0][keep] * d[keep]).sum() / N) if N > 0 else 0.0
    return (t, float(Pc[0]), float(M[0]), float(N), mean_d)


def _result(run, n, mol, sig, Pc, M, total_in, course, steps, draws, Vm) -> dict[str, Any]:
    r = _radii(n, mol, Vm)
    s2 = sig ** 2 + (run.p["sigma_intrinsic"] * draws["sig"])[:, None] ** 2
    r_med = r * np.exp(-1.5 * s2)          # log-normal whose mean volume is r^3
    d_med = 2e9 * r_med
    s = np.sqrt(s2)
    # number histogram over D_GRID_NM (cohort log-normals binned by CDF)
    z = (np.log(D_GRID_NM)[None, None, :] - np.log(np.maximum(d_med, 1e-12))[:, :, None]) / np.maximum(s, 1e-6)[:, :, None]
    cdf = ndtr(z)
    hist = (n[:, :, None] * np.diff(cdf, axis=2)).sum(axis=1)       # (D, bins), number per m3
    count = D_CENTERS_NM >= D_MIN_COUNT_NM
    h = hist[:, count]
    dc = D_CENTERS_NM[count]
    N = h.sum(axis=1)
    mean = (h * dc).sum(axis=1) / np.maximum(N, 1e-300)
    sd = np.sqrt(np.maximum((h * dc ** 2).sum(axis=1) / np.maximum(N, 1e-300) - mean ** 2, 0.0))
    final = Pc + M + mol.sum(axis=1)
    return {
        "hist": hist, "d_edges_nm": D_GRID_NM, "d_centers_nm": D_CENTERS_NM,
        "mean_nm": mean, "sd_nm": sd, "cv_pct": 100.0 * sd / np.maximum(mean, 1e-12),
        "number_per_m3": N,
        "reduced_frac": 1.0 - Pc / max(total_in, 1e-300),
        "mass_balance": {"in_mM": total_in, "out_mM": final.tolist(),
                         "rel_error": float(np.max(np.abs(final - total_in)) / max(total_in, 1e-300))},
        "course": {"t_s": [c[0] for c in course], "precursor_mM": [c[1] for c in course],
                   "monomer_mM": [c[2] for c in course], "n_per_m3": [c[3] for c in course],
                   "mean_d_nm": [c[4] for c in course]},
        "steps": steps,
    }


def nominal_draws(D: int = 1) -> dict[str, np.ndarray]:
    """All multipliers 1 / shifts 0 (the nominal parameter set)."""
    one, zero = np.ones(D), np.zeros(D)
    return {"nuc": zero.copy(), "k1": one.copy(), "k2": one.copy(), "ks": one.copy(),
            "eff": one.copy(), "dG": zero.copy(), "sig": one.copy(), "gamma": one.copy()}


def random_draws(D: int, seed: int = 0) -> dict[str, np.ndarray]:
    """Draw 0 nominal, others log-normal around it (assumed spreads, model.py docstring)."""
    rng = np.random.default_rng(seed)
    d = nominal_draws(D)
    if D > 1:
        z = rng.standard_normal((7, D - 1))
        d["nuc"][1:] = 0.5 * z[0]
        d["k1"][1:] = 10 ** (0.15 * z[1])
        d["k2"][1:] = 10 ** (0.15 * z[2])
        d["ks"][1:] = 10 ** (0.15 * z[3])
        d["eff"][1:] = 10 ** (0.2 * z[4])
        d["dG"][1:] = 0.02 * z[5]
        d["sig"][1:] = np.exp(0.2 * z[6])
    return d
