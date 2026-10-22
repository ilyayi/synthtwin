# Branch `design`: problem -> optimise -> robot proposals

## What was built

`synthtwin/design/` (all files < 400 lines, docstrings at the top of each):

| module | what it does |
|---|---|
| `problem.py` | `load(path) -> Problem` from yaml; validates knob keys against the canonical conditions keys and targets against known quantities; every problem is reported in one message |
| `calibrate.py` | `family(predictor, library, problem)`: library recipes of the material (+method) with outcomes and >= 2 conditions incl. `temperature_C` -> merged calibration dict (median over per-recipe `predictor.calibrate` calls), family spread (median relative deviation), n; n = 0 -> status "uncalibrated" and every band widened x2.5 (stated in the report) |
| `optimize.py` | `run(problem, predictor, calibration, seed=0, n_eval=80)`: Latin hypercube + L-BFGS-B refinement from the best 6 starts; objective = sum of weight x ((pred-value)/scale)^2 + min/max penalties at the band edge + 0.05 x (half-width/scale)^2; returns the 3 x n_proposals best candidates kept >= 0.12 apart in unit knob space; deterministic per seed; `in_validated_region` from `{method: {knob: [lo, hi]}}` (strict: every knob must be listed and inside) |
| `propose.py` | `make(problem, candidates, novelty_fn, robot, library)`: keeps novel + robot-feasible candidates; writes stock dispenses ("<name> <conc> mM (<role>)" stocks, volumes solved for the target final concentrations, water make-up), heating, stirring, reductant addition rate, ageing, UV-Vis 300-900 nm + DLS z-average/PDI measurements with predicted `lspr_nm`/`dls_z_nm`; controls = best-matching library recipe + a repeat of it; risks include every default the steps assumed |
| `run.py` | `synthtwin-design problem.yaml --library recipes.jsonl --robot robot.yaml --predictor mod [--validated v.json] [--seed] [--n-eval] --out DIR` -> `report.md` (problem; known recipes with sources; calibration; candidates; novelty with nearest recipe; proposals; assumptions) + `proposals.json`. Invalid problem: clear message, report only, exit 1. Valid problem, nothing novel+feasible: message + empty proposals, exit 1 |

Support: `examples/problem.yaml` (Au, 15 nm, CV <= 10 %, citrate; the brief's knobs),
`examples/robot.yaml` (generic liquid handler, marked as an example),
`examples/recipes.jsonl` (12 synthetic Turkevich-style Au recipes, source "manual",
each titled as made-up numbers; regenerate with `tools/gen_example_recipes.py`),
`tests/stubs/np_stub.py` (the brief's stub: size falls with
`ratio_reductant_precursor` and `temperature_C`, CV falls with temperature;
`predict` + `calibrate` per the simulator contract).

The predictor is loaded as `--predictor package.module` and must expose
`predict(params) -> {quantity: {value, low, high, unit}}` and
`calibrate(params, outcomes) -> dict`; `params` carries `material`, `method`,
`conditions`, `reagents`, `calibration`. `synthtwin/schemas.py` was not touched.

## Recipe search / novelty fallback

`synthtwin/recipes` (search + novelty) has not landed yet, so `run.py` imports it
lazily and otherwise uses a built-in material+method filter and an exact-match
novelty check (novel unless a library recipe has the identical conditions dict).
Every report states which was used, under Assumptions. When `synthtwin.recipes`
lands, its `search(library, problem)` and `novelty.check(candidate, library)`
are picked up automatically; if those signatures differ, only `run.py`'s two
adapters change.

## Tests

71 passed, 0 failed, offline (`nice -n 19 .venv/bin/python -m pytest`): 36
pre-existing benchmark tests + 35 new (problem 8, calibrate 5, optimize 7,
propose 8, end-to-end 7). The end-to-end tests run the real CLI on
`examples/` -> 3 proposals; determinism is checked by byte-comparing two
`proposals.json` outputs; the invalid-problem and cold-robot tests check the
clear-message/no-proposals paths.

## Example-run numbers (all synthetic)

`PYTHONPATH=tests/stubs synthtwin-design examples/problem.yaml ...`:

- calibration: **calibrated** on 12 family recipes, `size_scale = 0.906`,
  median relative deviation 3.1 %, band factor x1.03
- best candidate score ~ 0.000 (target hit inside the band): size_mean_nm
  15.0 (14.2-15.8), size_cv_pct 8.3 (7.7-8.9)
- 3 proposals at ratio 5.07-5.53, T 92.4-97.0 C, conc 0.66-0.92 mM; nearest
  known recipe (manual:np-example:06) at normalised distance 0.05-0.08,
  coverage "ok" (12 >= 3 family recipes)
- same run with a method filter that matches nothing -> "uncalibrated",
  bands widened x2.5, still 3 proposals (all labelled exploratory)

## Known gaps

- No real simulator yet (`synthtwin/np/model.py` lands separately); every number
  above comes from the stub and the synthetic library. No real-data validation.
- Exact-match novelty is weak on purpose (fallback only); distance-threshold
  novelty with tolerance < 1 waits for `synthtwin/recipes.novelty`.
- The validated-region check is strict: a method with only some knobs listed in
  `validated.json` marks its candidates exploratory. Deliberate, but worth
  revisiting once real validated ranges exist.
- `pH`, capping agents and seeded-growth knobs flow through generically
  (`conc_capping_mM`, `ratio_capping_precursor`) but no example exercises them.
- Determinism holds within one scipy version; there is no golden-file test on
  the example output (LHS draws can change between scipy versions).
- `docs/PIPELINE.md` also sketches `design/structure.py` (knobs -> dispersion);
  that belongs with the nanoparticle simulator branch, not this one.
