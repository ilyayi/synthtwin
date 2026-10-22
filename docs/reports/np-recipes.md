# Branch `np-recipes`: nanoparticle recipe library, search, novelty

`synthtwin/recipes/{__init__,chem,outcomes,ingest,search,novelty,cli}.py` +
console script `synthtwin-recipes`. No changes to `schemas.py`: everything
targets the general `Recipe` / `Reagent` / `Outcome` contract. pyarrow stays
an optional extra (`pip install -e '.[data]'`); pyyaml joined the base deps
for the problem yaml. Real-data output goes to gitignored `/data/`.

## What was built

- **chem.py** — material and reagent parsing. `parse_material` maps
  `Au nanoparticles`, `Trisoctahedral (TOH) Gold Nanocrystals`,
  `citrate-capped gold nanoparticles (Au NPs)`, `AuNPs` → `Au`;
  `Ag-Au alloy nanoparticles` → `Ag-Au`; `CdSe/ZnS quantum dots` →
  `CdSe-ZnS`; `TiO2`, `Fe3O4` keep formulas; descriptive materials survive
  as cleaned names (`graphene quantum dots` → `graphene`). `canon_name`
  collapses synonyms (`trisodium citrate dihydrate`/`Tribasic sodium citrate`
  → `citrate`, `Poly Vinyl Pyrrolidone` → `pvp`, `CTAB` and
  `(1-Hexadecyl) trimethylammonium chloride` → `ctab`/`ctac`,
  `tetrachloroaurate` → `haucl4`). `role_of` uses the role dictionary
  (HAuCl4/AgNO3 precursor, citrate/NaBH4/ascorbic acid reductant,
  PVP/CTAB/CTAC/oleylamine capping, solvents, base/acid, seed), falls back
  to element match for the target material (`Palladium(II) acetylacetonate`
  → precursor for Pd) and marks nanoparticle suspensions of the target
  (`Au nanosphere solution`) as seed. `parse_amount` converts units:
  mL/uL/L → volume_ml, mM/M/uM → conc_mM (molarity hidden in the purity
  field included). `moles_mmol` from conc×volume, or from mass via molar
  masses of the common salts (hydrate-aware for HAuCl4·3H2O).
- **outcomes.py** — `parse_outcomes(texts)` mines abstract, notes and step
  texts (first statement per quantity wins, source recorded):
  `15 ± 2 nm` → size_mean_nm + size_sd_nm with the method (TEM, SEM, DLS,
  UV-Vis, SAXS, XRD, AFM) from nearby words; `plasmon/SPR/absorption ...
  at 520 nm` → lspr_nm (300–1000 only, same sentence); hydrodynamic
  diameter → dls_z_nm, PDI → dls_pdi, `CV of 12 %` → size_cv_pct. A laser
  line or a deposited-layer thickness is never a size (particle-context
  words required; `hydrodynamic` is excluded from the size patterns).
- **ingest.lematsynth(paths, stats=None)** — a row is kept when the material
  name says nano-object (nanoparticle/nanorod/quantum dot/NP...; bare
  "particles/colloids" do not count, so colloidal crystals and active matter
  drop), the method is not physical (PVD/CVD/lithography/electro.../ball
  mill...), and at least one reagent has a synthesis role — that last rule
  drops the many characterization/device papers that carry a nano material
  name but no chemistry. Conditions use the canonical keys, taken from the
  first chemistry step that states them: temperature_C (K converted),
  time_min (s/h/days converted), pH, stirring_rpm, addition_rate_ml_min
  (`2 mL/min` in a description), total_volume_ml (sum of stated volumes),
  conc_{precursor,reductant,capping}_mM (final concentration from moles and
  total volume when computable, else the stated stock), and
  ratio_reductant_precursor from moles. Unreported keys land in `missing`.
  Method canonicalisation: seeded growth > reductant-specific (citrate /
  borohydride / ascorbic acid reduction) > green synthesis > chemical
  reduction > raw keyword (hydrothermal, sol-gel, ...). Dedup on
  (doi, material, method); `recipe_id = "lematsynth:<doi or
  sha1(title)[:12]>:<n>"`; extraction_score = evaluation overall_score.
- **search.search(problem, library, k=20)** — filters by material and
  allowed methods (empty = any), scores: outcome coverage of the problem's
  target quantities (2.0 × target weight each) + closeness of those outcomes
  to the targets (1.5; inside min/max = 1, point target graded by relative
  distance) + mean closeness of stated conditions to the knob bounds (1.5) +
  extraction score (1–5 normalised, ×0.5). One-line reason per hit
  (outcome vs target, knob in/out of bounds, extra outcomes, missing count).
- **novelty.check(candidate, library, tol=None) -> Novelty** — candidate as
  a `Recipe` or a dict of Recipe fields. Family = same material + method
  (unknown on either side keeps the recipe comparable), minus recipes that
  state a *different* reductant or capping name (different chemistry, not a
  repeat). `distance = max |diff|/tol` over condition keys known on both
  sides; default tolerances: ratio_* 20 % rel, conc_* 20 % rel,
  temperature_C 5, pH 0.5, time_min 50 % rel, addition_rate 50 % rel
  (total_volume/stirring 50 % rel, anything else 50 % rel). Novel iff
  nearest ≥ 1; < 3 family recipes → coverage "thin", never novel. Recipes
  sharing at least one condition always outrank condition-less ones in
  choosing the nearest (a blank recipe is distance 0 only because nothing
  is recorded). `tol` partially overrides the defaults.
- **CLI** — `synthtwin-recipes ingest <parquet...> --out recipes.jsonl`
  (prints rows read, nanoparticle recipes + duplicates dropped, per-material
  top 10, with size outcomes, with sd, with full conditions = T + time +
  ratio/conc) and `synthtwin-recipes search problem.yaml recipes.jsonl [-k]`.
  Example problem: `examples/np-problem.yaml`.

## Tests

114 pass (`pytest -q`); without pyarrow the 6 ingest/CLI tests skip (108).
Coverage: material/name/role/amount/mole parsing (test_chem), size/LSPR/DLS
mining incl. near-misses (test_outcomes), a synthetic-parquet end-to-end
with dedup and the row filters (test_ingest), filter/ranking/closeness
(search), novelty edge cases: identical, exactly-1, different reductant,
thin, blank-vs-sharing nearest, tolerance override (test_novelty), and the
CLI (test_recipes_cli).

## Real data (local LeMat-Synth dump, 3 parquet files, 58 345 rows)

Ingest ~3 s on the full dump → `data/recipes.jsonl` (gitignored):

- **260 recipes** (9 duplicate rows dropped): Au 39, Ag 21, Pt 9, Ni 8,
  ZnO 7, Cu 6, Pd 5, Si 5, carbon 5, C 4, + 127 more materials
  (Au/Ag family incl. alloys: 68).
- Methods (Au/Ag): seeded growth 16, other 14, chemical reduction 10,
  citrate reduction 9, solution synthesis 6, green synthesis 5, borohydride
  reduction 4, precipitation 2, ascorbic acid reduction 2.
- Conditions coverage: temperature_C 174/260, time_min 186/260, conc_* 32,
  ratio_reductant_precursor **1** (see gaps).
- Outcomes: size_mean_nm 24 (Au/Ag 11), size_sd_nm 6 (2), lspr_nm 3 (3).
  Sizes mostly live in figures/tables, not abstracts, so text mining finds
  a minority — the robot's own results are the intended dense source.
- Search on `examples/np-problem.yaml` (Au, 8 nm, citrate/seeded/borohydride):
  19 hits, top hit a citrate Au with size 17.9 ± 1.3 nm at 80 °C —
  outcome coverage and knob bounds visibly drive the ranking.
- Novelty on the real library: a 90 °C/20 min citrate Au candidate is novel
  (nearest distance 2.0, temperature 90 vs 100); a RT/12 h/pH 5 variant
  novel at 1.98; CdSe hot-injection is thin (no family recipes).

### 10 sample Au/Ag recipes (from data/recipes.jsonl)

| doi (or title) | mat. | method | reagents (first 3) | conditions | outcomes |
|---|---|---|---|---|---|
| 10.1021/nl302656d | Au | seeded growth | seed gold nanorods; solvent acetone; other graphene | T 70 °C; 30 min | size 20 nm |
| 10.1142/S1793292013500161 | Ag | chemical reduction | precursor silver nitrate; capping PVP; reductant ethylene glycol 6 mL | T 60 °C; 20 min; 206 mL | – |
| 10.1038/ncomms2956 | Au | other | other silicon; precursor gold | T 599.85 °C | size 10 nm |
| 10.1088/1361-6528/aa53f2 | Au | seeded growth | solvent acetone; other PMMA; solvent toluene 1 mL | T 140 °C; 1.6 min; 2 mL | size 20 nm |
| Extracellular biosynthesis of silver n… | Ag | green synthesis | other Pseudomonas sp.; precursor silver nitrate 1 mM | T 30 °C; 2880 min; conc_precursor 1 mM | lspr 410 nm |
| 10.1038/ncomms14910 | Ag | other | precursor Ag | T 700 °C; 90 min | – |
| 10.1021/acs.nanolett.0c03371 | Au | chemical reduction | other tetralin 20 mL; capping oleylamine 24.3 mL; precursor HAuCl4 | T 25 °C; 60 min; 48.8 mL; conc_precursor 12.1 mM | size 6 nm |
| 10.1002/cem.3507 | Ag | citrate reduction | precursor silver nitrate; reductant tribasic sodium citrate; base NaOH | T 100 °C; 5 min | – |
| 10.1021/acsanm.2c02524 | Au | citrate reduction | reductant tri-sodium citrate 5 mM; solvent water 100 mL; precursor HAuCl4 25 mM | T 100 °C; 20 min; 123 mL; conc_precursor 25 mM | – |
| Revealing the impact of polystyrene-fu… | Au | borohydride reduction | precursor hydrogen tetrachloroaurate 0.25 mL; capping CTAB 7.5 mL; reductant NaBH4 0.6 mL | T 27 °C; 15 min; 97.35 mL | – |

## Known gaps

- **ratio_reductant_precursor is almost never computable (1/260).** The
  structured amounts carry volumes or masses; the matching stock
  concentrations usually appear only inside step descriptions in prose. A
  prose pass (reagent name → nearby "38.8 mM") was deliberately not done:
  mis-pairing a concentration with the wrong reagent would poison ratios,
  and wrong numbers are worse than missing ones for calibration. Robot-made
  recipes and the simulator's own sweeps will populate this knob directly.
- Conditions flatten multi-stage syntheses: temperature/time come from the
  first chemistry step that states them, so a seed step made in an ice bath
  can be recorded as the recipe temperature when growth temperature is
  unreported.
- Outcome mining takes the first statement per quantity; sizes reported only
  in figures or tables are not extracted (LeMat-Synth has no structured
  outcomes). `basis` (number/volume/intensity) is not inferred.
- 92/260 recipes keep method "other" (raw LeMat-Synth label): the route
  cannot be inferred without reagent evidence; some are thermal/processing
  routes (599.85 °C from 873 K survives as "other").
- Novelty families are thin outside Au (Au citrate/borohydride/seeded have
  ≥ 3); most materials correctly report coverage "thin".
- Descriptive material names (no chemical token) can still be messy for
  carbon-nanotube/device rows that carry a chemistry reagent; they never
  collide with metal problems.
