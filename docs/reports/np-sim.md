# Branch `np-sim-local`: nanoparticle simulator (`synthtwin/np/`)

A physics-based forward model for Au and Ag colloid syntheses. It predicts the
size distribution, LSPR and DLS readouts that `synthtwin.design` and
`synthtwin.sweep` score against. The new code uses only numpy and scipy. All
parameters come from published literature or are marked "assumed"/"tuned" in
`params.py`.

## Modules

| file | lines | role |
|---|---|---|
| `synthtwin/np/params.py` | 273 | material, reductant, capping and method tables, each `(value, source)`; `get_params`, `sources`, `canon_method`, `PHYSICS_NAMES` |
| `synthtwin/np/chemistry.py` | 267 | recipe -> resolved run: concentrations, ratio/base handling, citrate pH charge balance, Au(III) hydrolysis speciation, Arrhenius rates, seeds/injections, calibration knobs |
| `synthtwin/np/growth.py` | 302 | ensemble kinetics: reduction (1st order + Finke-Watzky autocatalysis), CNT nucleation cohorts, diffusion/surface-limited growth with Gibbs-Thomson, Langmuir capping, Brownian coalescence below `coalescence_dmax_nm`; exact mass balance |
| `synthtwin/np/optics.py` | 211 | Johnson & Christy eps + size-dependent Drude damping, Bohren-Huffman coated-sphere Mie (core + ligand shell), ensemble absorbance, LSPR peak/FWHM |
| `synthtwin/np/dls.py` | 51 | Mie-intensity-weighted cumulant z-average and PDI (633 nm, 173 deg) |
| `synthtwin/np/model.py` | 231 | `predict`, `spectrum`, `calibrate`, `make_model`, `au`/`ag` sweep adapters |
| `synthtwin/np/data/johnson_christy_1972.csv` | - | n, k of Au and Ag, 0.64-6.60 eV (PRB 6, 4370) |
| `tests/test_np_sim.py` | 182 | 31 tests |

Quantities: `size_mean_nm`, `size_sd_nm`, `size_cv_pct`, `lspr_nm`,
`lspr_fwhm_nm`, `dls_z_nm`, `dls_pdi`. Each one is a band `{value, low, high, unit}`.
`value` is the nominal draw. `low` and `high` are the 5th and 95th percentiles
of a seeded ensemble (`n_draws`, default 16). The draws perturb the rate,
nucleation and growth constants and the dispensing within their literature
spreads.

## Optics checks (single sphere in water, citrate shell)

| particle | LSPR (nm) | expected (literature) |
|---|---|---|
| Au 20 nm | 522.6 (FWHM 80.0) | ~520-524 |
| Au 80 nm | 550.5 | ~545-555 |
| Ag 20 nm | 397.2 | ~395-405 |

- Mie extinction of a 5 nm Au sphere matches the quasi-static dipole limit within 3 %.
- Raw JC72 Ag with a clean surface puts the 20 nm peak at 387 nm. Ag particles carry a thin
  oxide/sulfide layer (E05), modelled as `surface_layer_dn = 0.3` on the
  shell index. This raises the peak to 397 nm.

## Mass balance

Over 9 families × 4 random draws, the largest relative error in the Au/Ag atom
balance (ions + monomer + particles + seeds) is 1.5e-15.

## Qualitative trend tests (nominal draw)

**Turkevich ratio** (Au citrate, 0.25 mM HAuCl4, 100 C, 30 min). Expected:
size falls from ratio 1 to ~4, then levels off (F73, J07).

| citrate:Au | 1 | 2 | 3.5 | 5 | 10 |
|---|---|---|---|---|---|
| d (nm) | 22.6 | 14.4 | 12.2 | 11.2 | 10.0 |
| CV (%) | 9.0 | 9.8 | 10.8 | 11.1 | 11.2 |
| pH | 4.36 | | 6.06 | | 6.77 |

At ratio 1, 81 % of the gold is reduced within 30 min.

**Temperature** (Au citrate, 90 min). Expected: hotter gives smaller and narrower particles.

| T (C) | 80 | 90 | 100 |
|---|---|---|---|
| d (nm) | 13.2 | 12.8 | 12.2 |
| CV (%) | 11.3 | 11.0 | 10.8 |

**NaBH4 vs citrate.** Expected: NaBH4 particles are below 6 nm and smaller than citrate particles.

| material | NaBH4 d (nm) | citrate d (nm) |
|---|---|---|
| Au | 3.03 | 12.1 |
| Ag | 3.43 | 60.3 (CV 17.8 %) |

**Seeded growth: volume scaling.** The reference is d = d_seed (1 + f_red / r)^(1/3),
where r = seed:precursor atom ratio. The test tolerance is 6 %.

| family | r | simulated d (nm) | formula (nm) |
|---|---|---|---|
| Ag | 0.005 | 58.35 | 58.58 |
| Ag | 0.02 | 36.93 | 37.08 |
| Au | 0.5 | 14.28 | 14.39 |
| Au | 1.0 | 12.50 | 12.60 |

**Sequential injections** (Au seeded, B11):
- 1 injection: 14.28 nm.
- 3 injections of 0.5 mM: 14.33 nm.

Injections grow the seeds without new nucleation.

**Tannic acid** (Au, P16). Expected: more TA gives smaller particles, in the 3.5-10 nm range.

| TA (mM) | 0.0025 | 0.01 | 0.05 |
|---|---|---|---|
| d (nm) | 7.67 | 5.69 | 4.04 |

**Base / pH** (Au citrate, NaOH added). Base raises the pH. That speeds the
citrate oxidation through the citrate charge state, but it also converts
AuCl4- into less reactive hydroxo species (W15, J07).

| NaOH (mM) | 0 | 0.25 | 0.5 | 1.0 |
|---|---|---|---|---|
| pH | 6.06 | 6.41 | 6.79 | 8.31 |
| d (nm) | 12.1 | 12.6 | 13.4 | 7.89 |

At pH 8.3, only 3 % of the gold is reduced in the default time.

**Hot injection** (Au, inverse order, S11): 11.4 nm, CV 9.9 %. The citrate
batch at the same conditions gives 12.1 nm.

## Physics overrides

The physics overrides are passed as `params["physics"] = {name: value}` to `predict`, `spectrum` and `calibrate`.

| name | default | source |
|---|---|---|
| `gamma_J_m2` | Au 0.30, Ag 0.25 | assumed effective solid/solution value (clean surface 1.5/1.25, TM77) |
| `Vm_m3_mol` | Au 1.021e-5, Ag 1.027e-5 | CRC (M / density) |
| `coalescence_dmax_nm` | 3.0 (0 disables) | assumed; P10, P12 |
| `coalescence_eff` | 0.02 | assumed |
| `capping_dG_eV` | citrate -0.30, tannic -0.45, PVP -0.40, CTAB -0.50, none 0 | assumed (Langmuir K = exp(-dG/kT)) |
| `ligand_shell_nm` | citrate 1.0, tannic 1.5, PVP 3.0, CTAB 3.2, none 0.3 | Park & Shumaker-Parry JACS 2014 (citrate); Gomez-Grana Langmuir 2012 (CTAB); others assumed |

Effect of each override on the default Au citrate case (one draw). The baseline is size 12.09 nm and
z-average 14.74 nm.

| override | result |
|---|---|
| `coalescence_dmax_nm = 0` | size 6.37 nm |
| `gamma_J_m2 = 0.4` | size 11.81 nm |
| `capping_dG_eV = -0.6` | size 5.27 nm |
| `ligand_shell_nm = 5` | z-average 22.74 nm |

## Timing (one `predict`, 16 draws, single core)

| family | s | size_mean_nm (nominal) | lspr_nm | dls_z_nm |
|---|---|---|---|---|
| Au citrate | 0.14 | 11.8 [9.77-15.4] | 523 | 14.4 |
| Ag citrate | 0.12 | 70.8 | 429 | |
| Au hot injection | 0.15 | | | |
| Au NaBH4 | 0.20 | 2.97 | 527 | 5.41 |
| Ag NaBH4 | 0.53 | 3.43 | 392 | |
| Au seeded | 0.12 | 14.3 | | |
| Ag seeded | 0.13 | 46.4 | 422 | 53.4 |
| Au tannic | 0.17 | 7.54 | | |
| Ag tannic | 0.45 | 5.2 | | 73 |

All are well under the 3 s budget. Calibrating one library recipe (2 knobs,
`least_squares`) takes 1-3 s.

## Calibration

`calibrate(params, outcomes)` fits one or two log10 knobs. The knobs are chosen per family:

| family | knobs |
|---|---|
| seeded | `log10_seed_scale`, `log10_growth_scale` |
| NaBH4 | `log10_nucleation_scale`, `log10_growth_scale` |
| others | `log10_growth_scale`, `log10_rate_scale` |

With one outcome, only the first knob is fitted. The tests check two recoveries:
- an Au citrate target of 18 nm, recovered within 5 %;
- an Ag seeded target of 30 nm plus a 35 nm z-average, recovered within 8 %.

## Integration

- `synthtwin-design ... --predictor synthtwin.np.model` loads the module. `calibrate` accepts
  `Outcome` objects, dicts or `{quantity: value}`. The example problem
  (`examples/problem.yaml`, 15 nm Au, CV <= 10 %) runs end to end in 3.6 min.
  Most of that time goes to the optimiser's L-BFGS-B refinement with finite
  differences. Calibration on the 12 synthetic library recipes gives
  `log10_rate_scale` -0.20 and `log10_growth_scale` 0.00, with a 20 % median
  deviation. The best candidate is ratio 1.6, 93 C, 0.40 mM, predicted at
  16.6 nm and CV 9.2 %.
- `synthtwin sweep baseline/score --model synthtwin.np.model:make_model` treats the flat sweep
  params as conditions for Au. Use `:ag` for Ag sweeps, because sweep params carry no
  material. A run on `examples/sweep_gold` (3 cases) takes 13 s.

## Limitations

- **Ag tannic.** The default (B14: 100 C, 0.025 mM TA) is bimodal: CV ~90 %,
  nominal mean ~4-5 nm, PDI 0.44. The reported ~10 nm seeds are not reproduced.
  Strong TA reduction at 100 C keeps nucleating. This family is untuned beyond
  mass balance, so treat its absolute numbers as unreliable.
- **Ag citrate.** Particles are large and broad (~60-70 nm, as in LM82). Absolute Ag
  numbers depend on the tuned `nuc_onset_mM`.
- **Shape.** All particles are spheres. Anisotropic shapes (rods, plates) are not modelled.
- **Constants.** Rate constants are effective values tuned on the default recipe of each family
  (marked "tuned" in `params.py`). Trends come from the physics. Absolute numbers
  should be calibrated on an anchor experiment.
