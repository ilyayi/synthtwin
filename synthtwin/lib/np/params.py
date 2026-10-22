"""Parameter sets for the nanoparticle simulator, each value with its source.

Every entry is `name: (value, source)`. "assumed" means no single published
number exists (an effective model constant); "tuned" means it was set so the
default recipe of a family lands on the typical published size cited next to
it. Called by chemistry.setup (recipe -> resolved run) and model.predict.

`get_params(material, method) -> dict` returns the flat parameter dict (values
only) for one (material, method) family; `sources(material, method)` returns
the matching {name: source}. Physics overrides (params["physics"] in
model.predict) replace entries of this dict by name - see model.py.

Method names are normalised by `canon_method` ("Turkevich", "citrate reduction",
"Frens" -> "citrate"; "inverse Turkevich", "hot injection" -> "hot_injection";
"NaBH4", "borohydride reduction" -> "borohydride"; "seed-mediated growth",
"seeded growth" -> "seeded"; "tannic acid", "tannic acid citrate" -> "tannic").

Main references (cited by key below):
  JC72   Johnson & Christy, Phys. Rev. B 6, 4370 (1972)
  TM77   Tyson & Miller, Surf. Sci. 62, 267 (1977) - solid surface energies
  CRC    CRC Handbook of Chemistry and Physics (densities, citrate pKa)
  AM76   Ashcroft & Mermin, Solid State Physics (1976), Table 2.1 (Fermi velocities)
  KV95   Kreibig & Vollmer, Optical Properties of Metal Clusters (Springer 1995)
  T51    Turkevich, Stevenson & Hillier, Discuss. Faraday Soc. 11, 55 (1951)
  F73    Frens, Nature Phys. Sci. 241, 20 (1973)
  J07    Ji et al., J. Am. Chem. Soc. 129, 13939 (2007) - pH / third role of citrate
  W15    Wuithschick et al., ACS Nano 9, 7052 (2015) - Turkevich mechanism, Au(III) speciation
  P10    Polte et al., J. Am. Chem. Soc. 132, 1296 (2010) - early coalescence of nuclei
  P12    Polte et al., ACS Nano 6, 5791 (2012) - Ag/NaBH4 formation by coalescence
  K07    Kumar, Gandhi & Kumar, Ind. Eng. Chem. Res. 46, 3128 (2007) - citrate -> DCA step
  S11    Sivaraman, Kumar & Santhanam, J. Colloid Interface Sci. 361, 543 (2011) - inverse order
  B11    Bastus, Comenge & Puntes, Langmuir 27, 11098 (2011) - seeded growth with injections
  B14    Bastus, Merkoci, Piella & Puntes, Chem. Mater. 26, 2836 (2014) - Ag citrate/TA
  P16    Piella, Bastus & Puntes, Chem. Mater. 28, 1066 (2016) - tannic-acid Au 3.5-10 nm
  LM82   Lee & Meisel, J. Phys. Chem. 86, 3391 (1982) - Ag citrate
  C79    Creighton, Blatchford & Albrecht, J. Chem. Soc. Faraday Trans. 2 75, 790 (1979)
  JGM01  Jana, Gearheart & Murphy, Langmuir 17, 6782 (2001) - NaBH4/citrate Au seeds ~3.5 nm
  FW97   Watzky & Finke, J. Am. Chem. Soc. 119, 10382 (1997) - autocatalytic surface growth
  E05    Elechiguerra et al., Chem. Mater. 17, 6042 (2005) - corrosion layer on Ag nanoparticles
  BH83   Bohren & Huffman, Absorption and Scattering of Light by Small Particles (Wiley 1983)
  V24    Vogel equation for water viscosity (standard fit A=2.414e-5 Pa s, B=247.8 K, C=140 K)
"""
from __future__ import annotations

import re
from typing import Any

# ----------------------------------------------------------------- materials
MATERIALS: dict[str, dict[str, tuple[Any, str]]] = {
    "Au": {
        "Vm_m3_mol": (1.021e-5, "CRC: 196.97 g/mol / 19.30 g/cm3"),
        "gamma_J_m2": (0.30, "assumed effective metal/solution interfacial energy (CNT + Gibbs-Thomson); the clean-surface value 1.5 J/m2 (TM77) applies in vacuum"),
        "valence": (3, "Au(III) -> Au(0)"),
        "D_monomer_m2_s": (1.0e-9, "assumed (small solute in water, 25 C; scaled by T/viscosity)"),
        "wp_eV": (9.03, "Drude plasma energy of Au, KV95"),
        "gamma_bulk_eV": (0.072, "Drude damping of Au fitted to JC72-type data (KV95 range 0.05-0.07)"),
        "vF_m_s": (1.40e6, "AM76"),
        "surface_layer_dn": (0.0, "clean Au surface"),
        "nuc_onset_mM": (2.0e-3, "tuned; Au(0) monomer level where homogeneous nucleation becomes fast (T51 sizes)"),
    },
    "Ag": {
        "Vm_m3_mol": (1.027e-5, "CRC: 107.87 g/mol / 10.50 g/cm3"),
        "gamma_J_m2": (0.25, "assumed effective metal/solution interfacial energy (CNT + Gibbs-Thomson); the clean-surface value 1.25 J/m2 (TM77) applies in vacuum"),
        "valence": (1, "Ag(I) -> Ag(0)"),
        "D_monomer_m2_s": (1.0e-9, "assumed (small solute in water, 25 C; scaled by T/viscosity)"),
        "wp_eV": (9.17, "Drude plasma energy of Ag, KV95"),
        "gamma_bulk_eV": (0.021, "Drude damping of Ag, KV95"),
        "vF_m_s": (1.39e6, "AM76"),
        "surface_layer_dn": (0.3, "assumed; index added to the ligand shell for the thin Ag2O/Ag2S surface layer of Ag colloids (E05); puts the 20 nm citrate-Ag peak at the measured ~395-400 nm"),
        "nuc_onset_mM": (5.0e-2, "tuned; Ag(0) clusters are less stable than Au(0) (higher onset); gives the large, broad LM82 particles"),
    },
}

# ---------------------------------------------------------- shared physics
COMMON: dict[str, tuple[Any, str]] = {
    "A_damping": (1.0, "assumed; surface-scattering constant in gamma = gamma_bulk + A vF/r, KV95 give 0.25-2"),
    "n_medium": (1.333, "water, visible range"),
    "nuc_barrier_ref_kT": (30.0, "assumed; Ceq is set so the CNT barrier is this many kT at nuc_onset_mM"),
    "log10_nuc_prefactor": (30.0, "assumed; CNT prefactor (m-3 s-1) ~ 1e30, calibration knob"),
    "k_surface_m_s": (1.0e-2, "assumed; surface-reaction velocity of monomer incorporation (near diffusion control)"),
    "k_surface_Ea_kJ_mol": (65.0, "assumed; activation energy of the surface step (reference 100 C), of the order of the reduction Ea"),
    "capping_block": (0.9, "assumed; fraction of growth/catalysis blocked at full capping coverage"),
    "coalescence_dmax_nm": (3.0, "assumed; P10 and P12 see nuclei of ~1-3 nm coalesce before growth"),
    "coalescence_eff": (0.02, "assumed; collision efficiency of small, partly capped clusters"),
    "coalescence_sigma": (0.15, "assumed; log-radius spread that coalescence relaxes towards (self-preserving-like)"),
    "sigma_intrinsic": (0.06, "assumed; particle-to-particle growth-rate scatter (log-normal width)"),
    "citrate_pKa": ((3.13, 4.76, 6.40), "CRC (25 C)"),
    "au_hydrolysis_pK": ((3.3, 6.0, 7.5, 9.0), "assumed; stepwise AuCl4- -> Au(OH)4- hydrolysis sequence as discussed in J07 and W15"),
    "au_species_reactivity": ((1.0, 0.4, 0.01, 0.001, 0.0001), "assumed; reactivity falls with each OH (J07, W15: hydroxylated Au(III) reacts slower)"),
}

# ----------------------------------------------------------------- reductants
# k1: homogeneous pseudo-first-order rate per mM of active reductant at T_ref_C (s-1 mM-1)
# k2: surface-catalysed (autocatalytic, FW97) rate per m2/m3 of particle area per mM (m s-1 mM-1)
# stoich: mol reductant consumed per mol metal reduced; tau_act_s: induction (activation) time at T_ref
REDUCTANTS: dict[str, dict[str, tuple[Any, str]]] = {
    "citrate": {
        "k1": (0.012, "tuned: T51 recipe (0.25 mM Au, ratio 3.5, 100 C) -> ~13-15 nm"),
        "k2": (5.0e-4, "tuned; surface-catalysed Au(III) reduction (W15)"),
        "Ea_kJ_mol": (88.0, "assumed; completion ~5 min at 100 C vs ~1 h at 70 C"),
        "T_ref_C": (100.0, "reference temperature for k1, k2"),
        "stoich_Au": (0.5, "assumed; citrate -> DCA, DCA reduces further (K07)"),
        "stoich_Ag": (0.25, "assumed; as for Au, one electron per Ag"),
        "tau_act_s": (25.0, "assumed; induction period of citrate -> dicarboxyacetone (K07)"),
        "ph_model": ("citrate", "reactive form is deprotonated citrate"),
        "Ag_factor": (0.005, "tuned: LM82 Ag citrate (1 mM, 100 C, 60 min) gives large, broad particles"),
    },
    "borohydride": {
        "k1": (40.0, "assumed; NaBH4 reduces Au(III)/Ag(I) within ms (P12)"),
        "k2": (0.0, "not needed: reduction is complete before particles grow"),
        "Ea_kJ_mol": (20.0, "assumed"),
        "T_ref_C": (25.0, "reference temperature"),
        "stoich_Au": (0.375, "BH4- gives 8 electrons"),
        "stoich_Ag": (0.125, "BH4- gives 8 electrons"),
        "tau_act_s": (0.0, "no induction"),
        "ph_model": ("none", ""),
        "Ag_factor": (1.0, ""),
    },
    "ascorbic": {
        "k1": (2.0e-6, "assumed; mild reductant, slow homogeneous path"),
        "k2": (1.0e-2, "assumed; reduction is surface catalysed on seeds"),
        "Ea_kJ_mol": (40.0, "assumed"),
        "T_ref_C": (25.0, "reference temperature"),
        "stoich_Au": (1.5, "ascorbate -> dehydroascorbate, 2 electrons"),
        "stoich_Ag": (0.5, "2 electrons"),
        "tau_act_s": (0.0, "no induction"),
        "ph_model": ("none", ""),
        "Ag_factor": (1.0, ""),
    },
    "tannic": {
        "k1": (50.0, "tuned: P16 (0.167 mM Au, 2.2 mM citrate, TA, 70 C) -> 3.5-10 nm"),
        "k2": (0.0, "assumed"),
        "Ea_kJ_mol": (40.0, "assumed"),
        "T_ref_C": (70.0, "reference temperature"),
        "stoich_Au": (0.05, "assumed; ~20 Au(III) per tannic acid (many galloyl groups)"),
        "stoich_Ag": (0.017, "assumed; ~60 Ag(I) per tannic acid"),
        "tau_act_s": (0.0, "no induction"),
        "ph_model": ("phenol", "phenolate is the active form; base speeds it up (P16 add K2CO3)"),
        "Ag_factor": (1.0, ""),
    },
}

# ------------------------------------------------------------------- capping
CAPPING: dict[str, dict[str, tuple[Any, str]]] = {
    "citrate": {"capping_dG_eV": (-0.30, "assumed; Langmuir K ~ 1e4-1e5 M-1 for citrate on Au"),
                "ligand_shell_nm": (1.0, "citrate layer ~1 nm (Park & Shumaker-Parry, JACS 136, 1907 (2014))"),
                "shell_n": (1.45, "assumed; refractive index of an adsorbed organic layer")},
    "tannic": {"capping_dG_eV": (-0.45, "assumed; TA adsorbs strongly on Au/Ag (P16)"),
               "ligand_shell_nm": (1.5, "assumed"),
               "shell_n": (1.50, "assumed; polyphenol layer")},
    "pvp": {"capping_dG_eV": (-0.40, "assumed; per repeat unit, conc in mM of repeat units"),
            "ligand_shell_nm": (3.0, "assumed; adsorbed PVP ~2-5 nm for PVP 10-55k"),
            "shell_n": (1.53, "CRC (PVP film)")},
    "ctab": {"capping_dG_eV": (-0.50, "assumed"),
             "ligand_shell_nm": (3.2, "CTAB bilayer ~3.2 nm (Gomez-Grana et al., Langmuir 28, 1453 (2012))"),
             "shell_n": (1.44, "assumed; surfactant bilayer")},
    "none": {"capping_dG_eV": (0.0, "no capping agent"),
             "ligand_shell_nm": (0.3, "assumed; bare surface + hydration layer"),
             "shell_n": (1.333, "water")},
}

# -------------------------------------------------------------------- methods
# default recipe per method and material (conditions keys as in schemas.Recipe)
METHODS: dict[str, dict[str, dict[str, tuple[Any, str]]]] = {
    "citrate": {
        "Au": {"reductant": ("citrate", "T51"), "capping": ("citrate", "T51"),
               "temperature_C": (100.0, "T51"), "conc_precursor_mM": (0.25, "T51"),
               "ratio_reductant_precursor": (3.5, "T51 (citrate:Au ~3.5)"),
               "time_min": (20.0, "T51")},
        "Ag": {"reductant": ("citrate", "LM82"), "capping": ("citrate", "LM82"),
               "temperature_C": (100.0, "LM82"), "conc_precursor_mM": (1.0, "LM82"),
               "ratio_reductant_precursor": (3.4, "LM82 (1% citrate, 2 mL per 100 mL)"),
               "time_min": (60.0, "LM82")},
    },
    "hot_injection": {
        "Au": {"reductant": ("citrate", "S11"), "capping": ("citrate", "S11"),
               "temperature_C": (100.0, "S11"), "conc_precursor_mM": (0.25, "S11"),
               "ratio_reductant_precursor": (3.5, "S11"), "time_min": (20.0, "S11"),
               "preheat_min": (15.0, "assumed; citrate boiled before Au is injected")},
        "Ag": {"reductant": ("citrate", "LM82"), "capping": ("citrate", "LM82"),
               "temperature_C": (100.0, "LM82"), "conc_precursor_mM": (1.0, "LM82"),
               "ratio_reductant_precursor": (3.4, "LM82"), "time_min": (60.0, "LM82"),
               "preheat_min": (15.0, "assumed")},
    },
    "borohydride": {
        "Au": {"reductant": ("borohydride", "JGM01"), "capping": ("citrate", "JGM01"),
               "temperature_C": (20.0, "JGM01"), "conc_precursor_mM": (0.25, "JGM01"),
               "ratio_reductant_precursor": (2.4, "JGM01 (0.6 mM NaBH4)"),
               "conc_capping_mM": (0.25, "JGM01 (0.25 mM citrate)"), "time_min": (10.0, "JGM01")},
        "Ag": {"reductant": ("borohydride", "C79"), "capping": ("none", "C79"),
               "temperature_C": (2.0, "C79 (ice bath)"), "conc_precursor_mM": (0.33, "C79"),
               "ratio_reductant_precursor": (2.0, "C79 (NaBH4 in excess)"), "time_min": (10.0, "C79")},
    },
    "seeded": {
        "Au": {"reductant": ("citrate", "B11"), "capping": ("citrate", "B11"),
               "temperature_C": (90.0, "B11"), "conc_precursor_mM": (0.167, "B11 (1 mL 25 mM per 150 mL)"),
               "conc_reductant_mM": (2.2, "B11"), "seed_d_nm": (10.0, "B11 seeds ~10 nm"),
               "seed_cv_pct": (8.0, "B11"), "ratio_seed_precursor": (0.5, "assumed"),
               "time_min": (30.0, "B11 (30 min per growth step)"), "n_injections": (1, "")},
        "Ag": {"reductant": ("ascorbic", "assumed"), "capping": ("pvp", "assumed"),
               "temperature_C": (25.0, "assumed"), "conc_precursor_mM": (1.0, "assumed"),
               "ratio_reductant_precursor": (2.0, "assumed"), "conc_capping_mM": (1.0, "assumed"),
               "seed_d_nm": (10.0, "assumed"), "seed_cv_pct": (10.0, "assumed"),
               "ratio_seed_precursor": (0.01, "assumed"), "time_min": (60.0, "assumed"),
               "n_injections": (1, "")},
    },
    "tannic": {
        "Au": {"reductant": ("citrate", "P16"), "capping": ("tannic", "P16"),
               "temperature_C": (70.0, "P16"), "conc_precursor_mM": (0.167, "P16"),
               "conc_reductant_mM": (2.2, "P16"), "conc_capping_mM": (0.0025, "P16 (TA, lower end)"),
               "conc_base_mM": (0.1, "P16 add K2CO3; here as mM of OH- equivalents (assumed)"), "time_min": (20.0, "P16"),
               "set_red_k2": (5.0e-3, "tuned: P16 growth completes within ~20 min at 70 C (faster surface-catalysed citrate path on TA-made nuclei, assumed)")},
        "Ag": {"reductant": ("citrate", "B14"), "capping": ("tannic", "B14"),
               "temperature_C": (100.0, "B14"), "conc_precursor_mM": (0.25, "B14"),
               "conc_reductant_mM": (5.0, "B14"), "conc_capping_mM": (0.025, "B14"),
               "time_min": (20.0, "B14")},
    },
}

# physics names the atomistic study may override (params["physics"])
PHYSICS_NAMES = ("gamma_J_m2", "Vm_m3_mol", "coalescence_dmax_nm", "coalescence_eff",
                 "capping_dG_eV", "ligand_shell_nm")

_METHOD_PATTERNS = [
    ("hot_injection", r"hot[\s_-]*inject|invers|revers"),
    ("tannic", r"tannic|tannin"),
    ("seeded", r"seed"),
    ("borohydride", r"borohydride|nabh4|kbh4"),
    ("citrate", r"citrat|turkevich|frens"),
]


def canon_method(method: str | None, conditions: dict[str, float] | None = None) -> str:
    """Free-text method -> one of METHODS. Seeds in the conditions imply seeded
    growth; unknown -> citrate (the most common NP route)."""
    low = (method or "").lower()
    for name, pattern in _METHOD_PATTERNS:
        if re.search(pattern, low):
            return name
    c = conditions or {}
    if any(k in c for k in ("ratio_seed_precursor", "conc_seed_mM", "seed_d_nm")):
        return "seeded"
    return "citrate"


def canon_material(material: str | None) -> str:
    m = (material or "Au").strip()
    return "Ag" if m.lower() in ("ag", "silver") else "Au"


def _entries(material: str, method: str) -> dict[str, tuple[Any, str]]:
    material = canon_material(material)
    method = canon_method(method)
    recipe = METHODS[method][material]
    out: dict[str, tuple[Any, str]] = {}
    out.update(COMMON)
    out.update(MATERIALS[material])
    out.update({f"default_{k}": v for k, v in recipe.items() if not k.startswith("set_")})
    red = REDUCTANTS[recipe["reductant"][0]]
    out.update({f"red_{k}": v for k, v in red.items()})
    out.update(CAPPING[recipe["capping"][0]])
    out.update({k[4:]: v for k, v in recipe.items() if k.startswith("set_")})  # family-specific values
    return out


def get_params(material: str, method: str) -> dict[str, Any]:
    """(material, method) -> flat {name: value} for this family (values only)."""
    return {k: v for k, (v, _src) in _entries(material, method).items()}


def sources(material: str, method: str) -> dict[str, str]:
    """(material, method) -> {name: source string} for every value of get_params."""
    return {k: src or "-" for k, (_v, src) in _entries(material, method).items()}
