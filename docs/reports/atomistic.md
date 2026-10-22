# Branch `atomistic`: atomistic parameters for the nanoparticle simulator

## Summary

`synthtwin/atomistic/` gives the simulator (`synthtwin/np/`) per-(material,
capping) values for its six physics override names. Each value carries an
uncertainty, a quality grade and its sources:

    from synthtwin.atomistic.params import physics_overrides
    params["physics"] = physics_overrides("Au", "citrate", strip=True)

Literature values (experiment and high-level DFT) are used wherever they
exist. No new DFT was run, because the published RPA, SCAN+rVV10 and
experimental surface energies are better than anything a few hours of PBE
slabs could give. Classical MD (LAMMPS, EAM) was used for the three questions
the literature does not answer for this size range:

1. Does the surface energy depend on size between 1.5 and 10 nm?
2. How much is the melting point depressed?
3. Do two touching clusters coalesce, and how does that depend on size and
   temperature?

Findings:

- **gamma.** The physical metal/water interfacial energy is 1.1-1.3 J/m2.
  The simulator defaults are 0.25-0.30 J/m2.
- **No size dependence.** The MD shows gamma within 3 % of the bulk value
  down to 87 atoms. The Tolman correction is negligible here.
- **Melting.** Clusters smaller than about 1.1-1.5 nm are liquid-like at
  synthesis temperatures.
- **Contact.** Bare clusters fuse irreversibly on every contact, at every size
  tested (1.5-8 nm).
- **Rounding.** Full rounding within nanoseconds happens only at about
  1.5 nm (Au; 2 nm at 550 K). Larger necked dimers stall, and the residual
  elongation grows steadily with size; Ag lags Au by about 1 nm. This supports a
  coalescence cutoff of a few nm, not the tens of nm that a continuum
  (Herring d^4) sintering law would allow.
- **Collision efficiency.** DLVO/Fuchs gives about 1 for bare clusters,
  against the default 0.02. The simulator already scales coalescence by
  (1 - theta), so capping still suppresses it.
- **Does it help?** Partly, and it showed why the simulator works.
  - Plugged in as a set with one anchor re-fit, the values do *not* improve
    the literature checks: the physical gamma broadens the CVs to 25-55 %.
  - The cause is CNT nucleation with gamma about 1.25 J/m2, which is almost
    insensitive to monomer depletion (nucleation order about 1). It is not
    Gibbs-Thomson ripening.
  - Adding a steep nucleation law (order about 19, through existing keys)
    to the physical set brings the CVs back to the defaults' accuracy (6/7
    in range). The default gamma of 0.3 is therefore a proxy for burst
    nucleation, not a surface energy.
  - The MD and DLVO results also say the small default coalescence_eff
    (0.02) stands in for stabilisation that bare clusters do not have.
  - See "Does it help" below.

### Recommended overrides (value +- 1 sigma)

| material | capping | gamma_J_m2 | Vm_m3_mol | coalescence_dmax_nm | coalescence_eff | capping_dG_eV | ligand_shell_nm |
|---|---|---|---|---|---|---|---|
| Au | none | 1.28 +- 0.12 | 1.021e-05 | 3.0 +- 1.5 | 0.75 +- 0.25 | 0.00 +- 0.00 | 0.3 +- 0.2 |
| Au | citrate | 1.24 +- 0.12 | 1.021e-05 | 3.0 +- 1.5 | 0.75 +- 0.25 | -0.35 +- 0.08 | 1.5 +- 0.7 |
| Au | tannic | 1.26 +- 0.12 | 1.021e-05 | 3.0 +- 1.5 | 0.75 +- 0.25 | -0.60 +- 0.20 | 2.0 +- 1.0 |
| Au | pvp | 1.25 +- 0.12 | 1.021e-05 | 3.0 +- 1.5 | 0.75 +- 0.25 | -0.25 +- 0.15 | 2.5 +- 1.0 |
| Au | ctab | 1.21 +- 0.13 | 1.021e-05 | 3.0 +- 1.5 | 0.75 +- 0.25 | -0.45 +- 0.15 | 3.2 +- 0.5 |
| Ag | none | 1.15 +- 0.11 | 1.027e-05 | 2.5 +- 1.5 | 0.75 +- 0.25 | 0.00 +- 0.00 | 0.3 +- 0.2 |
| Ag | citrate | 1.09 +- 0.12 | 1.027e-05 | 2.5 +- 1.5 | 0.75 +- 0.25 | -0.40 +- 0.10 | 1.4 +- 0.7 |
| Ag | tannic | 1.13 +- 0.11 | 1.027e-05 | 2.5 +- 1.5 | 0.75 +- 0.25 | -0.60 +- 0.20 | 2.0 +- 1.0 |
| Ag | pvp | 1.12 +- 0.11 | 1.027e-05 | 2.5 +- 1.5 | 0.75 +- 0.25 | -0.25 +- 0.15 | 2.5 +- 1.0 |
| Ag | ctab | 1.08 +- 0.12 | 1.027e-05 | 2.5 +- 1.5 | 0.75 +- 0.25 | -0.45 +- 0.15 | 3.2 +- 0.5 |

Grades: gamma_J_m2 moderate, Vm_m3_mol strong, coalescence_dmax_nm weak, coalescence_eff moderate, capping_dG_eV moderate, ligand_shell_nm moderate (capping-dependent grades: see the capping table). Values at T = 348 K; simulator defaults for comparison: gamma 0.25-0.30 J/m2, coalescence_eff 0.02, coalescence_dmax_nm 3.

## Contents

| file | what |
|---|---|
| `synthtwin/atomistic/literature.py`, `data/literature.json` | 89 literature entries. Each has value, unit, uncertainty, method, conditions, full citation, DOI and a `verified` flag (false = bibliographic data or number not re-checked in the paper). `load`, `query`, `combine`, `cite` |
| `synthtwin/atomistic/md.py`, `lammps/*.in` | LAMMPS driver and input templates: bulk, slabs, clusters, melting ramps, dimer coalescence (as-cut and annealed starts). GPU job queue with an 83 C thermal watchdog. `--stage analyze` writes the CSV/JSON summaries and needs no LAMMPS |
| `data/md_*.csv/json` | MD summaries (bulk/slab, clusters, melting, coalescence, down-sampled xi(t) series) |
| `synthtwin/atomistic/derive.py` | literature + MD -> `data/derived_params.json` (gamma chain, Pawlow fits, coalescence statistics, DLVO/Fuchs efficiency, capping table) |
| `synthtwin/atomistic/params.py` | `physics_overrides(material, capping=None, strip=False)` and `table()` |
| `synthtwin/atomistic/helps.py` | runs the simulator with default vs atomistic parameters on literature checks. Needs `synthtwin.np` |
| `tests/test_atomistic.py` | 27 tests (15 functions), no LAMMPS or simulator needed |

Reproduce:

    python -m synthtwin.atomistic.md --lmp $(which lmp) --potdir $LAMMPS/potentials \
        --gpus 0,1 --stage all          # ~45 job-hours, ~13 GPU-h
    python -m synthtwin.atomistic.md --stage analyze
    python -m synthtwin.atomistic.derive

## Methods

**Potential.** EAM, Foiles, Baskes & Daw, PRB 33, 7983 (1986), the `Au_u3`
and `Ag_u3` funcfl files. LAMMPS (stable 2Aug2023 and later) ran with
KOKKOS-CUDA (`-k on g 1 -sf kk`) on one RTX 3070 Ti workstation (2 GPUs) and
on three RTX 3090s of a shared server. All runs used NVT (Nose-Hoover), 4 fs
for Au and 3 fs for Ag.

**Bulk and slabs.** The bulk lattice constant and cohesive energy come from a
box/relax. Slab energies for (111), (100) and (110) used true periodic
lengths and 6-12 layers.

**Clusters.** Spheres were cut from fcc and minimised. They were annealed for
200 ps at 500 K, cooled to 100 K and minimised again; the lower of the two
energies is kept.

- Excess energy: E_ex = E - N e_coh.
- gamma_eff = E_ex / (pi d_eq^2), with d_eq = (6 N v_at / pi)^(1/3).
- A fit E_ex = a N^(2/3) + b N^(1/3) gives the Gibbs-Thomson
  gamma_GT = (dE_ex/dN) r / (2 v_at), the quantity that enters
  dmu = 2 gamma v / r.
- Sizes: d = 1.5, 2, 2.5, 3, 4, 5, 6, 8 and 10 nm (87 to 30 885 atoms).

**Melting.** The annealed clusters were heated linearly from 300 to 1400 K
over 1 ns (1.1 K/ps). Tm is where the liquid fraction, measured between the
solid and liquid potential-energy baselines, passes 0.5. The Pawlow fit
Tm(d) = Tm_b (1 - alpha/d) uses d >= 2 nm.

**Coalescence.**

- *Setup.* Two equal clusters: the second is rotated by a random angle
  (20-70 deg) about a random axis. They are equilibrated for 20 ps at an
  8 A gap with per-particle momentum zeroed, moved to a 2.5 A gap, then
  run for 2 ns.
- *Grid.*
  - As-cut spheres: d = 1.5, 2, 2.5, 3, 4, 5 and 6 nm, at T = 300, 373, 450
    and 550 K, with 3 replicas (2 at 6 nm). An extra 8 nm set ran at 300 and
    450 K, 1 ns, 1 replica.
  - Annealed (faceted) clusters: d = 2, 3, 4 and 5 nm, at 300 and 373 K, with
    2 replicas.
- *Progress measure.* From the principal moments of the gyration tensor,
  s = sqrt(l_max / l_min). Two touching spheres give s = sqrt(6); a compact
  particle gives about 1.0-1.1. The normalised elongation is
  xi = (s - 1.05) / (sqrt(6) - 1.05).
- *Completion.* "Fully rounded" means the 20-ps running mean of xi falls
  below 0.2 within the run (tau80).
- *Slow-phase rate.* The rate of xi decrease between t_run/4 and the end of
  the run is also recorded, to test a size-scaling extrapolation.

**What was not run, and why.**

- No DFT. The literature RPA/SCAN surface energies and isotherm free energies
  are better than new PBE slabs. PBE underbinds Au/Ag surfaces by about 40 %
  (Patra 2017).
- No explicit-ligand MD. A meaningful citrate/PVP/CTAB-on-Au force field
  (e.g. INTERFACE-FF) plus water needs about 10^5 atoms per nm-scale pair,
  which is not affordable in this budget. The ligand effect therefore enters
  only through the literature-bounded capping dG, the shells, and the
  simulator's (1 - theta) factor.

## Literature basis

`data/literature.json` holds 89 entries (surface energies by facet and method, Tolman lengths, melting data, adsorption energies/isotherm free energies, ligand shell thicknesses, Hamaker constants, coalescence observations). Entries used directly in the derived values:

| id | quantity | value | method | reference |
|---|---|---|---|---|
| goss15_Cl_Ag111 | adsorption_energy | -1.6 +- 0.2 eV | DFT-PBE slab (VASP) | F. Gossenberger, doi:10.1016/j.susc.2014.01.021 |
| goss15_Br_Ag111 | adsorption_energy | -1.54 +- 0.2 eV | DFT-PBE slab (VASP) | F. Gossenberger, doi:10.1016/j.susc.2014.01.021 |
| zhang25_OH_Ag111_pbe | adsorption_energy | -1.67 +- 0.3 eV | DFT-PBE slab | Z. Zhang, doi:10.48550/arXiv.2507.20496 |
| carrasco14_benzene_Ag111_exp | adsorption_energy | -0.69 +- 0.05 eV | experiment (TPD, Campbell-Sellers prefactor correction) | J. Carrasco, doi:10.1063/1.4866175 |
| alsaidi12_PVP_Ag | adsorption_energy |  | DFT-PBE+vdW(TS) slab, 2-pyrrolidone + ethane fragments | Al-Saidi, doi:10.1021/nl2041113 |
| goss15_Cl_Au111 | adsorption_energy | -0.97 +- 0.2 eV | DFT-PBE slab (VASP) | F. Gossenberger, doi:10.1016/j.susc.2014.01.021 |
| goss15_Br_Au111 | adsorption_energy | -0.99 +- 0.2 eV | DFT-PBE slab (VASP) | F. Gossenberger, doi:10.1016/j.susc.2014.01.021 |
| zhang25_OH_Au111_pbe | adsorption_energy | -1.01 +- 0.3 eV | DFT-PBE slab | Z. Zhang, doi:10.48550/arXiv.2507.20496 |
| santiago14_HCOO_Au111_rpbe | adsorption_energy | -1.29 +- 0.3 eV | DFT-RPBE (non-self-consistent on PW91 geometry) | Y. Santiago-Rodriguez, doi:10.1016/j.susc.2014.04.012 |
| pekoz16_phenol_Au111_revpbevdw | adsorption_energy | -0.64 +- 0.14 eV | DFT-vdW-DF (revPBE-vdW) slab (VASP) | R. Pekoz, doi:10.1063/1.4962236 |
| pekoz16_phenol_Au111_vdwdf2 | adsorption_energy | -0.77 +- 0.14 eV | DFT-vdW-DF2 (PW86-vdW2) slab (VASP) | R. Pekoz, doi:10.1063/1.4962236 |
| carrasco14_benzene_Au111_exp | adsorption_energy | -0.76 +- 0.05 eV | experiment (TPD, Campbell-Sellers prefactor correction) | J. Carrasco, doi:10.1063/1.4866175 |
| dinkel16_MPS_Au_dG | adsorption_energy | -0.48 +- 0.05 eV | experiment (SHG adsorption isotherm, modified Langmuir) | Dinkel, doi:10.1021/acs.jpcc.5b11055 |
| dinkel18_MPS_Au5nm_dG | adsorption_energy | -0.41 +- 0.05 eV | experiment (SHG adsorption isotherm) | Dinkel, doi:10.1021/acs.jpcc.8b07897 |
| cardenas22_citrate_Ag | ligand_shell_thickness | 1.94 +- 0.3 nm | SV-AUC + STEM (core-shell sedimentation fit) | P. Cardenas Lopez, doi:10.1039/D2NR02633C |
| cardenas22_citrate_Au | ligand_shell_thickness | 2.19 +- 0.3 nm | SV-AUC + STEM (core-shell sedimentation fit) | P. Cardenas Lopez, doi:10.1039/D2NR02633C |
| nanocomposix_TA_Au10 | ligand_shell_thickness | 3 +- 1 nm | DLS minus TEM ((D_h - D_TEM)/2) | nanoComposix (Fortis Life Sciences) |
| gomezgrana12_CTAB_bilayer_Au | ligand_shell_thickness | 3.2 +- 0.5 nm | SAXS / SANS of CTAB-capped Au nanorods | S. Gomez-Grana, doi:10.1021/la203451p |
| parkshumaker14_citrate_Au | ligand_shell_thickness | 1 +- 0.5 nm | STM / IR of citrate layers on Au(111) and Au NPs | J.-W. Park, doi:10.1021/ja4097384 |
| tysonmiller77_Ag_avg | surface_energy_avg | 1.25 +- 0.13 J/m2 | experiment (liquid-metal surface tension extrapolation) | W. R. Tyson, doi:10.1016/0039-6028(77)90442-3 |
| patra17_scanrvv10_Ag_avg | surface_energy_avg | 1.22 +- 0.07 J/m2 | DFT-SCAN+rVV10 slab (facet mean) | A. Patra, doi:10.1073/pnas.1713320114 |
| patra17_rpa_Ag_avg | surface_energy_avg | 1.42 +- 0.1 J/m2 | RPA (as tabulated) | A. Patra, doi:10.1073/pnas.1713320114 |
| tysonmiller77_Au_avg | surface_energy_avg | 1.5 +- 0.15 J/m2 | experiment (liquid-metal surface tension extrapolation) | W. R. Tyson, doi:10.1016/0039-6028(77)90442-3 |
| patra17_scanrvv10_Au_avg | surface_energy_avg | 1.29 +- 0.07 J/m2 | DFT-SCAN+rVV10 slab (facet mean) | A. Patra, doi:10.1073/pnas.1713320114 |
| patra17_rpa_Au_avg | surface_energy_avg | 1.41 +- 0.1 J/m2 | RPA (as tabulated) | A. Patra, doi:10.1073/pnas.1713320114 |

## MD results

### Bulk and slabs (EAM vs literature)

| | a0 (A) | e_coh (eV) | gamma(111) | gamma(100) | gamma(110) (J/m2) |
|---|---|---|---|---|---|
| Au EAM | 4.080 | -3.93 | 0.786 | 0.915 | 0.977 |
| Ag EAM | 4.090 | -2.85 | 0.617 | 0.702 | 0.764 |
| Au exp. avg. (Tyson-Miller) / RPA avg. | | | 1.50 / 1.41 | | |
| Ag exp. avg. (Tyson-Miller) / RPA avg. | | | 1.25 / 1.42 | | |

The EAM values reproduce Foiles 1986. EAM underestimates absolute surface
energies by 30-40 % (sphere-averaged cluster value 0.97 vs 1.40 J/m2 for Au,
0.76 vs 1.30 J/m2 for Ag), like PBE. The MD is therefore used only for *ratios*
and *trends* (size dependence, sphere vs facet, melting, kinetics), never for
the absolute gamma.

### Cluster surface energy vs size (EAM, annealed)

gamma in J/m2 (EAM).

| d (nm) | Au N | Au gamma_eff | Au gamma_GT | Ag N | Ag gamma_eff | Ag gamma_GT |
|---|---|---|---|---|---|---|
| 1.5 | 87 | 0.928 | 0.979 | 87 | 0.746 | 0.768 |
| 2 | 249 | 0.939 | 0.975 | 225 | 0.786 | 0.766 |
| 2.5 | 459 | 0.976 | 0.973 | 459 | 0.796 | 0.765 |
| 3 | 887 | 0.990 | 0.971 | 791 | 0.779 | 0.765 |
| 4 | 1985 | 0.994 | 0.970 | 1961 | 0.770 | 0.764 |
| 5 | 3925 | 0.970 | 0.969 | 3805 | 0.773 | 0.764 |
| 6 | 6699 | 0.977 | 0.968 | 6603 | 0.761 | 0.763 |
| 8 | 15707 | 0.963 | 0.967 | 15683 | 0.756 | 0.763 |
| 10 | 30885 | 0.971 | 0.967 | 30669 | 0.767 | 0.763 |

The fit gives:

| | a (eV) | b (eV) | gamma_inf (J/m2) |
|---|---|---|---|
| Au | 1.924 | 0.252 | 0.965 |
| Ag | 1.527 | 0.105 | 0.762 |

gamma_GT changes by less than 1.3 % between 2 and 10 nm (Au +1.2 % at 1.5 nm),
in line with the small negative Tolman lengths of Molleman & Hiemstra 2018
(-0.03 to -0.04 nm). The **size factor applied to gamma is therefore
1.00 +- 0.02**.

The sphere-averaged value is 1.23 x gamma(111) for both metals. This is the
average over the facets, edges and vertices of a real cluster. It is why the
isotropic literature averages (Tyson-Miller, Patra) are used rather than
(111) values.

### Melting-point depression

| d (nm) | Au N | Au Tm (K) | Ag N | Ag Tm (K) |
|---|---|---|---|---|
| 1.5 | 87 | 417 | 87 | 626 |
| 2 | 249 | 698 | 225 | 738 |
| 3 | 887 | 882 | 791 | 932 |
| 4 | 1985 | 941 | 1961 | 999 |
| 5 | 3925 | 1002 | 3805 | 1038 |
| 6 | 6699 | 1035 | 6603 | 1077 |
| 8 | 15707 | 1077 | 15683 | 1119 |

Pawlow fits on d >= 2 nm:

| | Tm_b (K) | alpha (nm) | rms (K) |
|---|---|---|---|
| Au | 1202 +- 6 | 0.84 | 6 |
| Ag | 1238 +- 10 | 0.77 | 10 |

- EAM-u3 bulk Tm is about 1150-1250 K (experiment: Au 1337 K, Ag 1235 K).
- Experiment for Au (Buffat & Borel 1976, about 600 K at 2 nm) gives
  alpha = 1.10 nm.
- Clusters are liquid at the synthesis temperature (348 K) below
  d* = alpha / (1 - T/Tm_b): **1.2 nm (Au, EAM), 1.1 nm (Ag, EAM) and 1.5 nm
  (Au, experiment)**.
- The 87-atom Au cluster shows no clear melting transition; it is already
  liquid-like or amorphous at 400 K.

### Dimer coalescence


**as-cut start**: final xi, mean (sd) [fraction fully rounded, xi <= 0.2], n replicas

| material | T (K) | 1.5 nm | 2 nm | 2.5 nm | 3 nm | 4 nm | 5 nm | 6 nm | 8 nm |
|---|---|---|---|---|---|---|---|---|---|
| Au | 300 | 0.29 (0.12) [0.33], n=3 | 0.47 (0.06) [0.00], n=3 | 0.44 (0.07) [0.00], n=3 | 0.62 (0.03) [0.00], n=3 | 0.75 (0.03) [0.00], n=3 | 0.77 (0.02) [0.00], n=3 | 0.85 (0.01) [0.00], n=2 | 0.88 (0.00) [0.00], n=1, 1 ns |
| Au | 373 | 0.31 (0.08) [0.33], n=3 | 0.36 (0.07) [0.00], n=3 | 0.52 (0.05) [0.00], n=3 | 0.58 (0.06) [0.00], n=3 | 0.74 (0.02) [0.00], n=3 | 0.74 (0.01) [0.00], n=3 | 0.84 (0.02) [0.00], n=2 |  |
| Au | 450 | 0.21 (0.15) [0.67], n=3 | 0.39 (0.09) [0.00], n=3 | 0.51 (0.04) [0.00], n=3 | 0.58 (0.04) [0.00], n=3 | 0.72 (0.02) [0.00], n=3 | 0.75 (0.03) [0.00], n=3 | 0.84 (0.01) [0.00], n=2 | 0.86 (0.00) [0.00], n=1, 1 ns |
| Au | 550 | 0.09 (0.03) [1.00], n=3 | 0.26 (0.12) [0.33], n=3 | 0.35 (0.03) [0.00], n=3 | 0.43 (0.05) [0.00], n=3 | 0.68 (0.03) [0.00], n=3 | 0.70 (0.03) [0.00], n=3 | 0.79 (0.01) [0.00], n=2 |  |
| Ag | 300 | 0.49 (0.07) [0.00], n=3 | 0.61 (0.08) [0.00], n=3 | 0.80 (0.01) [0.00], n=3 | 0.82 (0.01) [0.00], n=3 | 0.90 (0.01) [0.00], n=3 | 0.84 (0.01) [0.00], n=3 | 0.92 (0.00) [0.00], n=2 | 0.91 (0.00) [0.00], n=1, 1 ns |
| Ag | 373 | 0.54 (0.12) [0.00], n=3 | 0.68 (0.03) [0.00], n=3 | 0.77 (0.04) [0.00], n=3 | 0.81 (0.00) [0.00], n=3 | 0.88 (0.01) [0.00], n=3 | 0.83 (0.01) [0.00], n=3 | 0.90 (0.01) [0.00], n=2 |  |
| Ag | 450 | 0.44 (0.12) [0.00], n=3 | 0.67 (0.06) [0.00], n=3 | 0.70 (0.09) [0.00], n=3 | 0.72 (0.01) [0.00], n=3 | 0.87 (0.03) [0.00], n=3 | 0.83 (0.04) [0.00], n=3 | 0.90 (0.02) [0.00], n=2 | 0.92 (0.00) [0.00], n=1, 1 ns |
| Ag | 550 | 0.34 (0.02) [0.00], n=3 | 0.63 (0.05) [0.00], n=3 | 0.74 (0.04) [0.00], n=3 | 0.76 (0.07) [0.00], n=3 | 0.85 (0.03) [0.00], n=3 | 0.81 (0.02) [0.00], n=3 | 0.89 (0.01) [0.00], n=2 |  |


**annealed start**: final xi, mean (sd) [fraction fully rounded, xi <= 0.2], n replicas

| material | T (K) | 2 nm | 3 nm | 4 nm | 5 nm |
|---|---|---|---|---|---|
| Au | 300 | 0.51 (0.02) [0.00], n=2 | 0.64 (0.13) [0.00], n=2 | 0.73 (0.01) [0.00], n=2 | 0.80 (0.01) [0.00], n=2 |
| Au | 373 | 0.46 (0.12) [0.00], n=2 | 0.62 (0.06) [0.00], n=2 | 0.77 (0.00) [0.00], n=2 | 0.78 (0.02) [0.00], n=2 |
| Ag | 300 | 0.63 (0.01) [0.00], n=2 | 0.87 (0.03) [0.00], n=2 | 0.90 (0.00) [0.00], n=2 | 0.89 (0.01) [0.00], n=2 |
| Ag | 373 | 0.55 (0.07) [0.00], n=2 | 0.85 (0.03) [0.00], n=2 | 0.89 (0.04) [0.00], n=2 | 0.87 (0.01) [0.00], n=2 |

dPE (eV/atom, mean over T and replicas, as-cut): Ag 1.5 nm -0.053; Ag 2 nm -0.030; Ag 2.5 nm -0.026; Ag 3 nm -0.013; Ag 4 nm -0.006; Ag 5 nm -0.006; Ag 6 nm -0.003; Ag 8 nm -0.004; Au 1.5 nm -0.086; Au 2 nm -0.061; Au 2.5 nm -0.053; Au 3 nm -0.027; Au 4 nm -0.014; Au 5 nm -0.011; Au 6 nm -0.007; Au 8 nm -0.004

Observations:

1. **Contact always leads to fusion.** A neck forms within 10-20 ps at every
   size and temperature, with dPE < 0 (-0.09 eV/atom at 1.5 nm,
   -0.007 eV/atom at 6 nm). No dimer separated. With bare surfaces,
   "aggregation" and "coalescence" therefore differ only in how fast the
   necked pair rounds up.
2. **Rounding needs a small size or a high temperature.**
   - Au 1.5 nm rounds fully (xi <= 0.2) within 2 ns in 1/3 of the runs at
     300-373 K, 2/3 at 450 K and all runs at 550 K. The completion time falls
     from about 0.7 ns at 450 K to about 0.2 ns at 550 K (apparent
     activation about 0.3 eV). Au 2 nm completes only at 550 K (1/3).
   - Ag never reaches 0.2. Ag 1.5 nm ends at xi = 0.3-0.5, an elongated
     compact cluster.
3. **Residual elongation grows steadily with size, and the necked pair
   stalls.** After 2 ns, Au sits at xi of about 0.3 (1.5 nm), 0.45
   (2-2.5 nm), 0.6 (3 nm), 0.75 (4-5 nm) and 0.85 (6-8 nm). Ag is higher
   at every size: Ag at d behaves roughly like Au at d + 1 nm.
   - Temperature matters only below about 3 nm.
   - The slow-phase rate (t_run/4 to the end) is at most about 0.03 /ns and
     changes sign between replicas: a plateau, not a measurable approach.
   - A power-law (Herring) size-scaling fit was attempted and abandoned,
     because sizes above 1.5 nm give no finite completion times. A d^4
     extrapolation from 1.5 nm would put the cutoff at tens of nm for a
     1 ms-1 s collision interval. The stall instead matches the
     faceted/nucleation-limited regime, where shape change waits for new
     facet layers to nucleate: Combe, Jensen & Pimpinelli PRL 85, 110 (2000),
     and the in-situ TEM + KMC of Lim et al. ACS Nano 2009 (faceted Au
     particles round over seconds to minutes, not by continuum sintering).
   - *What this does not show:* 2 ns cannot rule out rounding of 3-5 nm
     dimers on micro- to milliseconds. The MD fixes the *ordering* (size,
     Au vs Ag, weak T dependence) and the lower bracket; the upper bracket
     comes from experiment.
4. **Annealed vs as-cut starts.** Faceted, annealed clusters stall at the same
   or larger xi as cut spheres of the same size, so the stall is not an
   artefact of the rough starting surfaces.

Caveats:

- Vacuum, no ligands or solvent. Water and ligands slow surface diffusion,
  and the simulator's (1 - theta) factor removes coalescence of capped
  particles anyway.
- 2 ns is about 10^6 times shorter than a collision interval. EAM surface
  diffusion barriers are roughly right for Ag(111) (EAM about 0.06-0.1 eV vs
  0.097 eV STM; Brune 1995), but step-edge barriers are not checked.
- One potential family only.

## Derived parameters

### gamma_J_m2

For each metal:

    gamma = [gamma_sv(lit, 0 K) + dT + water] x size factor (MD)
            (- Ma 2012 combination, Ag) + ligand term

| material | capping | gamma_sv lit 0 K | dT | water | size factor | ligand | gamma |
|---|---|---|---|---|---|---|---|
| Au | none | 1.40 +- 0.11 | -0.03 | -0.10 | 1.005 | +0.000 | **1.28 +- 0.12** |
| Au | citrate | 1.40 +- 0.11 | -0.03 | -0.10 | 1.005 | -0.041 | **1.24 +- 0.12** |
| Au | tannic | 1.40 +- 0.11 | -0.03 | -0.10 | 1.005 | -0.012 | **1.26 +- 0.12** |
| Au | pvp | 1.40 +- 0.11 | -0.03 | -0.10 | 1.005 | -0.024 | **1.25 +- 0.12** |
| Au | ctab | 1.40 +- 0.11 | -0.03 | -0.10 | 1.005 | -0.070 | **1.21 +- 0.13** |
| Ag | none | 1.30 +- 0.11 | -0.03 | -0.10 | 1.003 | +0.000 | **1.15 +- 0.11** |
| Ag | citrate | 1.30 +- 0.11 | -0.03 | -0.10 | 1.003 | -0.056 | **1.09 +- 0.12** |
| Ag | tannic | 1.30 +- 0.11 | -0.03 | -0.10 | 1.003 | -0.012 | **1.13 +- 0.11** |
| Ag | pvp | 1.30 +- 0.11 | -0.03 | -0.10 | 1.003 | -0.024 | **1.12 +- 0.11** |
| Ag | ctab | 1.30 +- 0.11 | -0.03 | -0.10 | 1.003 | -0.070 | **1.08 +- 0.12** |

- **gamma_sv.** The unweighted mean of experiment (Tyson & Miller 1977),
  RPA and SCAN+rVV10 (Patra 2017):
  - Au: 1.40 +- 0.11 J/m2.
  - Ag: 1.30 +- 0.11 J/m2.
  - PBE (0.84-0.87) is excluded because it underbinds.
- **dT.** -0.03 +- 0.03 J/m2 for 0 K -> 300-373 K. Au goes from 1.50 at 0 K
  (TM77) to 1.38 at Tm (Buffat-Borel), about -0.09 mJ/m2/K.
- **water.** -W_adh by Young-Dupre:
  0.072 x (1 + cos theta) = 0.10-0.14 J/m2 for theta = 0-60 deg (clean Au is
  hydrophilic; Smith 1980). Taken as -0.10 +- 0.04 J/m2.
- **Size factor.** 1.00 +- 0.02 (MD above).
- **Ag only.** The Ag value is combined (inverse variance) with the in-water
  Kelvin fit of Ma et al. 2012 (1.0 +- 0.3 J/m2).
- **Ligand term.** Gibbs/Szyszkowski: -Gamma_max R T ln(1 + K c), at 348 K
  and a reference concentration (citrate 1 mM, TA 0.05 mM, PVP 1 mM RU, CTAB
  1 mM).

### coalescence_dmax_nm

- **Au: 3.0 +- 1.5 nm. Ag: 2.5 +- 1.5 nm. Grade: weak.**
- **Lower end.** Coalescence is certain where the clusters are liquid-like
  at 348 K (1.1-1.5 nm) or round within nanoseconds in MD (Au 1.5 nm).
- **Upper end.** Faceted few-nm particles round on the seconds-minutes scale
  observed in situ (Lim 2009). In MD the shape relaxation stalls more and
  more from 2 nm up (observation 3).
- **Ag below Au.** Ag dimers round more slowly in MD at every size and
  temperature, by about 1 nm. The offset is set to only 0.5 nm because
  destabilised Ag particles of tens of nm neck and coalesce at room
  temperature in experiments (Magdassi 2010). EAM-u3 Ag may be too sluggish,
  and in water the halide and oxide chemistry of Ag surfaces speeds up
  surface transport.
- **Comparison with the default.** The value confirms the simulator default
  (3 nm) instead of replacing it, but now with MD evidence for the ordering
  and against the continuum alternative (tens of nm).

### coalescence_eff

- **0.75 +- 0.25 (both metals). Grade: moderate.**
- **DLVO/Fuchs.**
  - Model: Fuchs stability ratio W, with a sphere-sphere Hamaker term and a
    linear-superposition double layer.
  - Monte Carlo over d = 1.5-3 nm, A = 1.5-3.5e-19 J, psi = -15 to -45 mV,
    I = 1-10 mM and T = 348 K.
  - Result: 1/W median 1.20 (16-84 %: 1.00-1.31). The maximum barrier is
    about 0.2 kT: nm clusters have no electrostatic barrier, because the
    barrier scales with a psi^2.
- **Hydrodynamic retardation.** Lowers the collision rate by a factor 0.5-1,
  taken as x 0.75.
- **MD.** Shows sticking on every contact.
- **Comparison with the default.** The default 0.02 is about 40 x lower. In
  the simulator this rate is further multiplied by (1 - theta). A low eff
  therefore stands in for partial capping or electrostatic stabilisation that
  the model already has elsewhere.

### capping_dG_eV and ligand_shell_nm

Langmuir theta = Kc/(1+Kc), K = exp(-dG/kT)/(1 M). dG is a free energy of adsorption from water at the reference state 1 M, with the ligand displacing water. Literature ids for each row are in `derived_params.json` (`lit_dG`, `lit_shell`).

| capping | dG Au (eV) | dG Ag (eV) | grade | basis | shell Au / Ag (nm) | grade | basis |
|---|---|---|---|---|---|---|---|
| none | 0.00 +- 0.00 | 0.00 +- 0.00 | strong | no capping agent | 0.3 +- 0.2 / 0.3 +- 0.2 | weak | hydration/counter-ion layer, judgement |
| citrate | -0.35 +- 0.08 | -0.40 +- 0.10 | moderate | bounded above in strength by the thiolate isotherm free energies on Au (Dinkel 2016 -0.48 eV, Dinkel 2018 -0.41 eV on 5 nm NPs): carboxylate binds more weakly than thiolate and is displaced by thiols; Ag stronger than Au by the DFT O/halide binding offset (OH, Cl: Ag - Au = -0.6..-0.7 eV in vacuum, scaled down for solvation): judgement | 1.5 +- 0.7 / 1.4 +- 0.7 | moderate | dense layer ~1.0 nm (Park & Shumaker-Parry 2014) to solvated shell ~2 nm (Cardenas Lopez 2022) |
| tannic | -0.60 +- 0.20 | -0.60 +- 0.20 | weak | per molecule: multidentate galloyl/phenol binding; single phenol/benzene on Au(111)/Ag(111) -0.64..-0.97 eV in vacuum with vdW-DFT, reduced by water displacement; weak | 2.0 +- 1.0 / 2.0 +- 1.0 | weak | TA molecule ~2 nm; 3.0 nm vendor hydrodynamic shell is an upper bound |
| pvp | -0.25 +- 0.15 | -0.25 +- 0.15 | weak | per repeat unit (carbonyl O-metal + vdW, weak per unit, strong per chain); Ag(100) > Ag(111) qualitatively (Al-Saidi 2012); judgement, weak | 2.5 +- 1.0 / 2.5 +- 1.0 | weak | adsorbed PVP loops/tails, judgement (2-4 nm for 10-55 kDa PVP) |
| ctab | -0.45 +- 0.15 | -0.45 +- 0.15 | weak | Br- headgroup layer: vacuum DFT Br on Au(111) -0.99 eV, Ag(111) -1.54 eV (vs 1/2 Br2), strongly reduced by hydration; bilayer cooperativity; judgement, weak | 3.2 +- 0.5 / 3.2 +- 0.5 | moderate | CTAB bilayer (Gomez-Grana 2012) |

## Does it help?

`python -m synthtwin.atomistic.helps` ran the simulator (branch
`np-sim-local`, commit 86325f5) with one draw per case.

**Cases.** Seven literature recipes with approximate size and CV ranges:

- Turkevich/Frens citrate:Au at 1:1, 3.5:1 and 10:1, at 100 C;
- NaBH4 Au and Ag;
- tannic acid Au;
- Lee-Meisel Ag.

**Score.** The |log| distance outside the literature range, 0 inside.

**Calibration.** "+ nuc cal" re-fits only `log10_nucleation_scale` on the
Turkevich 3.5:1 anchor (13 nm). The simulator's defaults were tuned by hand
to these same trends, so this comparison favours the defaults.

| case | lit d (nm) | lit CV (%) | default | gamma only | coalescence only | capping+shell only | physical (all six) | physical except gamma | default + nuc cal | physical + nuc cal | physical + steep nuc + nuc cal |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Au citrate 1:1 | 20-40 | 10-25 | 22.6 / 9 | 20.5 / 21 | 28.2 / 12 | 16.9 / 10 | 19.8 / 25 | 20.3 / 14 | 33.1 / 14 | 18.4 / 26 | 19.3 / 14 |
| Au citrate 3.5:1 | 12-16 | 8-15 | 12.2 / 11 | 11.8 / 26 | 14.8 / 18 | 9.7 / 10 | 14.2 / 27 | 12.7 / 18 | 13.0 / 13 | 13.0 / 29 | 13.1 / 14 |
| Au citrate 10:1 | 10-20 | 8-20 | 10.0 / 11 | 9.7 / 26 | 12.5 / 20 | 8.0 / 9 | 12.1 / 28 | 11.3 / 16 | 10.2 / 13 | 11.4 / 30 | 11.4 / 12 |
| Au NaBH4 | 3-6 | 10-30 | 3.0 / 16 | 6.3 / 45 | 2.8 / 35 | 3.0 / 16 | 6.4 / 53 | 3.0 / 18 | 3.2 / 37 | 5.5 / 54 | 3.0 / 16 |
| Ag NaBH4 | 5-15 | 15-40 | 3.0 / 32 | 10.3 / 49 | 2.3 / 62 | 3.0 / 32 | 10.9 / 54 | 2.3 / 62 | 5.8 / 43 | 9.5 / 54 | 2.4 / 36 |
| Au tannic 0.01 mM | 4-10 | 5-15 | 5.0 / 16 | 6.6 / 23 | 4.5 / 43 | 3.3 / 14 | 5.8 / 22 | 4.7 / 15 | 5.8 / 17 | 5.6 / 20 | 4.4 / 14 |
| Ag citrate (Lee-Meisel) | 40-80 | 20-50 | 58.4 / 18 | 34.7 / 17 | 59.1 / 19 | 52.3 / 18 | 32.4 / 17 | 52.4 / 18 | 112.8 / 23 | 26.4 / 16 | 44.1 / 15 |

Cells: mean diameter (nm) / CV (%). Summary (size score excludes the anchor):

| variant | size err | sizes in range | CV err | CVs in range |
|---|---|---|---|---|
| default | 0.083 | 5/6 | 0.041 | 4/7 |
| gamma only | 0.037 | 3/6 | 0.288 | 1/7 |
| coalescence only | 0.146 | 4/6 | 0.273 | 2/7 |
| capping+shell only | 0.183 | 1/6 | 0.017 | 5/7 |
| physical (all six) | 0.048 | 3/6 | 0.334 | 1/7 |
| physical except gamma | 0.132 | 5/6 | 0.111 | 3/7 |
| default + nuc cal | 0.057 | 5/6 | 0.055 | 4/7 |
| physical + nuc cal | 0.084 | 4/6 | 0.352 | 0/7 |
| physical + steep nuc + nuc cal | 0.134 | 3/6 | 0.045 | 6/7 |

Fitted log10_nucleation_scale: default -3.44, physical 0.49, physical_steep 0.41.

Reading:

- **gamma alone** lowers the size error (0.037 vs 0.083). Ag NaBH4 moves into
  range (10.3 nm; default 3.0 nm), while Au NaBH4 (6.3 nm) and Lee-Meisel Ag
  (35 nm) land just outside theirs. But the CVs suffer: 1/7 in range.
- **Capping alone** (dG and shells) leaves the CVs good. It makes the
  particles about 20 % smaller (stronger citrate and tannic binding than the
  defaults), so without a re-fit the sizes are off: 1/6 in range.
- **Coalescence alone** (eff 0.75, dmax 3/2.5 nm) broadens the CVs of the
  uncapped Ag NaBH4 (62 %) and the low-tannic case (43 %). Here the defaults'
  small eff was doing real work (H2).
- **All six with an anchor re-fit**: sizes 4/6 in range, CVs 0/7 in range.
  The anchor re-fit moves log10_nucleation_scale by only +0.5 (default -3.4).
  With the physical gamma the CNT prefactor is about right as it stands.
- **All six + steep nucleation + anchor re-fit**: CVs 6/7 in range (CV error
  0.045, defaults 0.041), sizes 3/6 in range. The size misses are Ag NaBH4
  (2.4 nm vs 5-15 nm), the 1:1 Turkevich (19.3 vs 20-40 nm) and Au NaBH4
  (2.95 vs 3-6 nm, just below). This is the configuration we recommend for
  the benchmark (H1).
- Seven qualitative cases and one draw each: this is a sanity check of
  mechanisms, not a validation.

Hypotheses this leaves for the benchmark:

- **H1. Physical gamma is usable if the nucleation law is steep, and that
  is why the effective gamma works (tested).** The simulator sets the bulk
  solubility Ceq so that the CNT barrier is `nuc_barrier_ref_kT` = 30 kT at
  `nuc_onset_mM`. With gamma = 0.3 J/m2 this gives ln S_onset of about 6, and
  a nucleation order n* = d ln J / d ln S = 2 x 30 / ln S of about 10: a
  burst that stops as soon as the monomer is drawn down.
  - With physical gamma (about 1.25 J/m2), B grows as gamma^3, ln S_onset is
    about 55 and n* is about 1. Nucleation then barely notices monomer
    depletion and continues through growth, so the CVs broaden to 25-55 %.
    This, not Gibbs-Thomson ripening, is the mechanism: with Ceq that low,
    the solubility term is negligible at every size.
  - The test: keep the physical gamma and raise the reference barrier to
    200 kT, with the prefactor raised by 170/ln 10 decades so the onset stays
    put (n* about 19). Re-fit only the anchor. The CVs then come back to
    6/7 in range (CV error 0.045 vs 0.041 for the defaults); sizes are 3/6
    in range vs 5/6.
  - So gamma = 0.25-0.30 in the default set is a stand-in for "burst
    nucleation". The physics behind it is not the surface energy. It is
    that nucleation of Au(0)/Ag(0) is much steeper in S than CNT with bulk
    gamma predicts. This fits the known failure of CNT for sub-nm metal
    clusters: the critical nucleus is below one atom, and the MD shows
    clusters below about 1.2-1.5 nm are liquid-like.
  - *Recommendation:* use the physical gamma for growth and Gibbs-Thomson,
    and expose the nucleation order as its own parameter (`helps.STEEP`
    shows one way, through existing keys). Do not tune gamma to get CVs.
- **H2. Coalescence eff of about 1 is right for bare clusters.**
  Coalescence should be limited by capping (theta) and by dmax, not by a
  small eff. With eff = 0.75, the simulator over-coalesces the only uncapped
  recipe (NaBH4 Ag: 2.3 nm, CV 62 % with "coalescence only" vs 3.0 nm, CV
  32 % with the defaults).
  - This points to early stabilisation that the model does not represent:
    in real NaBH4 syntheses, BH4-/borate and the excess ions adsorb
    (Creighton 1979, Mulfinger 2007).
  - *Prediction (not testable without code changes):* the simulator
    currently gives theta = 0 when no capping agent is present. Treating
    borohydride/borate as a weak capping agent (dG of about -0.2 eV) would
    fix this case better than a global eff = 0.02.
- **H3. Capping dG.** Citrate -0.35 eV (Au, vs -0.30 default) shifts
  Turkevich sizes down by about 20 % (12.2 -> 9.7 nm at 3.5:1, capping only). The anchor calibration absorbs this, so it is not testable
  without independent coverage data.
- **H4. Shells.** The shells only move DLS z-average and the LSPR shift by
  2 x the shell thickness, by construction. Testable directly on DLS-vs-TEM
  pairs from the recipe library.

## Timings

All MD ran in about 2.6 h of wall-clock time (14:10-16:50 on the run day) on
two machines:

- **Workstation, 2 x RTX 3070 Ti.** 1 job per GPU plus 1-2 single-core CPU
  slots, about 2.3 h of device time per GPU (about 4.5 GPU-h).
- **Shared server, 3 x RTX 3090.** Up to 4 jobs per GPU plus 4 CPU slots,
  about 2.6 h (about 8 GPU-h).

In total that is **about 12-13 GPU-hours of device occupancy plus about
12 CPU-core-hours**. Small systems (1.5-2.5 nm, 200-1000 atoms) ran as fast
or faster on one CPU core than on a shared GPU, so the queue mixes both.
The "job-hours" below are the sum of per-job wall times; they double-count
GPUs shared by several jobs, so they are *not* GPU-hours. A thermal
watchdog paused jobs at 83 C (it triggered twice on one workstation GPU
during the 8 nm runs). No DFT was run: 0 CPU-hours.

| study | jobs | job-hours (sum of wall time) | median wall per job |
|---|---|---|---|
| clusters (anneal + minimise) | 18 | 0.39 | 70 s |
| melting ramps | 14 | 0.67 | 169 s |
| dimer coalescence | 196 | 44.04 | 675 s |
| **total** | | **45.1** | |

Coalescence median wall time per job (s):

| start | material | 1.5 nm | 2 nm | 2.5 nm | 3 nm | 4 nm | 5 nm | 6 nm | 8 nm |
|---|---|---|---|---|---|---|---|---|---|
| as-cut | Au | 195 | 521 | 979 | 1146 | 1202 | 1448 | 1638 | 343 |
| as-cut | Ag | 193 | 518 | 1431 | 572 | 272 | 1584 | 1740 | 476 |
| annealed | Au |  | 132 |  | 208 | 215 | 269 |  |  |
| annealed | Ag |  | 147 |  | 645 | 281 | 357 |  |  |

## Grades and limitations

| parameter | grade | why |
|---|---|---|
| Vm_m3_mol | strong | CRC density |
| gamma_J_m2 (as a physical quantity) | moderate | literature spread +-0.1; water and ligand corrections are model estimates; *how it is used* in the simulator is the weak point: only physical with a steep nucleation law (H1) |
| coalescence_eff | moderate | robust no-barrier result for nm clusters; hydrodynamic factor estimated |
| coalescence_dmax_nm | weak | MD fixes the lower bracket (1.5 nm certain) and the ordering (stall grows with size; Ag slower than Au) but cannot reach synthesis times; the final value is a judgement within 1.5-5 nm |
| capping_dG_eV citrate | moderate | bounded by thiolate isotherms (Dinkel) and DFT trends; no direct citrate isotherm found |
| capping_dG_eV tannic, PVP, CTAB | weak | vacuum DFT of fragments (phenol, benzene, Br) and judgement; solvation not computed |
| ligand_shell_nm citrate, CTAB | moderate | measured (Park 2014, Cardenas Lopez 2022; Gomez-Grana 2012) |
| ligand_shell_nm tannic, PVP, none | weak | molecular size / judgement |

Other limits:

- EAM only; absolute surface energies are 30-40 % low (used only for ratios).
- Vacuum MD.
- 2 ns windows.
- Replicas: 3 (as-cut, d <= 5 nm), 2 at 6 nm and for annealed starts, 1 at
  8 nm.
- `verified: false` literature entries (bibliography confirmed, number not
  re-read) are flagged in the JSON.
