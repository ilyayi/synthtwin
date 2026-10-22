# SynthTwin

Can a simulation predict a published catalysis experiment it has not seen?

A **case** is one published CO-oxidation light-off sweep: one paper, one variable
changed (Pt loading, calcination temperature, ageing time, ...), three or more samples,
each with a measured light-off temperature T50. The predictor sees a **card** with
the recipes and exactly one measured point, the **anchor**. It may calibrate one
nuisance parameter on the anchor, then predicts T50 with an uncertainty band for
every sample. The other measurements stay sealed in a **vault** until scoring.

## Scores

| score | over | meaning |
|---|---|---|
| `trend_ok` | all points | Spearman >= 0.8 (n >= 4), or the exact rank order (n = 3). The headline. |
| `spearman` | all points | rank agreement with the measured T50s |
| `t50_mae_K` | held-out points | mean absolute T50 error |
| `band_coverage` | held-out points | fraction of measured T50s inside the predicted band |

A prediction that skips a point is never `trend_ok`, and the skipped point counts as
outside its band.

Two reference predictors set the floor. `null` predicts the anchor T50 for every
point. `baseline` runs a light-off model calibrated on the anchor, with no agent.

## Use

```
pip install -e '.[test]'
python -m synthtwin.cli build examples/gold cards vault        # split gold -> cards + sealed vault
python -m synthtwin.cli baseline cards --predictor null -o null.jsonl
python -m synthtwin.cli baseline cards --predictor baseline \
    --model mypkg.lightoff:predict_lightoff -o base.jsonl
python -m synthtwin.cli score cards vault null.jsonl            # scores.jsonl + a markdown table
```

A light-off model is any function `params -> {"t50_K", "t50_K_low", "t50_K_high",
"log10_site_scale_used"}`. When `params` holds `calibrate_t50_K`, the model fits its
own `log10_site_scale` to that T50 and reports the value it used.

## General sweeps

The same machinery runs on any conditions -> outcomes sweep (first use:
Au/Ag nanoparticles: size and size distribution vs ratios, pH, seed loading).
A `SweepCase` card reveals one anchor point's measured **outcomes** (any number
of quantities, e.g. `size_mean_nm` and `size_cv_pct`); a predictor returns a
band for every quantity at every point, and each quantity is scored separately
(spearman, mae, band_coverage, trend_ok as above).

```
python -m synthtwin.cli sweep build examples/sweep_gold cards vault
python -m synthtwin.cli sweep baseline cards --predictor null -o null.jsonl
python -m synthtwin.cli sweep baseline cards --predictor model \
    --model mypkg.np:make_model -o base.jsonl
python -m synthtwin.cli sweep score cards vault base.jsonl
```

A simulator is any class or factory `fn` with `predict(params) ->
{quantity: {value, low, high, unit}}` and `calibrate(params, outcomes) ->
extra params for predict`. It is calibrated on the anchor's outcomes and then
predicts each point with that point's conditions. `synthtwin/lib/sweep.py` holds
the split, leak scan (held-out values of all quantities, no unit shift),
scoring and baselines.

## Design

The same machinery designs new experiments: a stated problem becomes robot-ready
proposals through library search, calibration, optimisation and a novelty check
(`docs/PIPELINE.md`).

```
pip install -e '.[test]'
PYTHONPATH=tests/stubs synthtwin-design examples/problem.yaml \
    --library examples/recipes.jsonl --robot examples/robot.yaml \
    --predictor np_stub --out out
```

`--predictor` names a module with `predict(params) -> {quantity: {value, low,
high, unit}}` and `calibrate(params, outcomes) -> dict` (`tests/stubs/np_stub.py`
is the deterministic stub used in tests; `synthtwin.np.model` is the real
nanoparticle simulator, see below). Recipe search and novelty come from `synthtwin.recipes`
when installed; until then a built-in material+method filter and an exact-match
novelty check are used and the report says so. The example library, robot and
problem are synthetic illustrations, not real data.

## Nanoparticle simulator

`synthtwin/lib/np/` is a physics-based forward model for Au and Ag colloids. It
needs only numpy and scipy. It covers citrate (Turkevich/Frens, including
hot injection), NaBH4, seeded growth (including `n_injections`) and tannic-acid
syntheses. It runs Arrhenius and pH-dependent reduction, nucleation, growth and
coalescence, then Mie optics and DLS. Each quantity (`size_mean_nm`,
`size_sd_nm`, `size_cv_pct`, `lspr_nm`, `lspr_fwhm_nm`, `dls_z_nm`, `dls_pdi`)
is returned as a band from a seeded ensemble. One predict takes well under a
second.

```
synthtwin-design examples/problem.yaml --library examples/recipes.jsonl \
    --robot examples/robot.yaml --predictor synthtwin.np.model --out out
python -m synthtwin.cli sweep baseline cards --predictor model \
    --model synthtwin.np.model:make_model -o base.jsonl   # :ag for Ag sweeps
```

```python
from synthtwin.np import model
model.predict({"material": "Au", "method": "citrate", "conditions": {"temperature_C": 90},
               "physics": {"coalescence_dmax_nm": 0, "capping_dG_eV": -0.4}})
```

`params["physics"]` overrides physical constants by name: `gamma_J_m2`,
`Vm_m3_mol`, `coalescence_dmax_nm`, `coalescence_eff`, `capping_dG_eV`,
`ligand_shell_nm`. These are the entry point for atomistic results. Every
default and its source is in `synthtwin/lib/np/params.py`. The trend tests and
optics checks are in `docs/reports/np-sim.md`.

## Data

- `examples/gold/` contains three **synthetic** cases with made-up numbers. They are
  for tests and for trying the tools.
- Real cases are built from open-access papers. Two independent readers digitise each
  figure blind to each other, and a point is kept only if they agree within 10 K
  (`tools/merge_readings.py`). The real gold answers are **not** in this repository.
  Publishing them would let future models train on the answers.
- A vault is written with dir mode 700 and file mode 600. It carries a random canary,
  and `leak_scan` flags any file containing the canary or three or more held-out T50
  values (in K or °C). Run it over everything a predictor could see.

## Layout

Everything about one pipeline step lives in one folder (`synthtwin/steps/<step>/`: its step.json
registry entry, its protocol, its LLM schema, its handlers, its UI panel); the science several
steps share is in `synthtwin/lib/`, the orchestrator and shared machinery in `synthtwin/core/`.
See docs/PIPELINE.md "Repo layout" for the full map.

```
synthtwin/steps/        one folder per UI step, in order: goal, prior, stack, sample, bench,
                        case, recipe, robot (step.json + protocol.md + schema.py + run.py +
                        panel.js/panel.css)
synthtwin/lib/          the shared science: np/ (colloid forward model), atomistic/, recipes/
                        (recipe library: LeMat-Synth ingest, search, novelty — CLI:
                        synthtwin-recipes), design/ (problem -> optimise -> robot proposals —
                        CLI: synthtwin-design), screen/, cards (gold case -> card + vault),
                        vault (sealed storage, leak scanning), score, baseline, sweep
synthtwin/core/         engine (the study agent orchestrator), llm, schemas (card, vault,
                        prediction and score formats), runner, catalog, systems, toolbox
synthtwin/protocols/    the cross-cutting protocols + the versioned protocol registry
synthtwin/agent/        import shims to the pre-steps paths
synthtwin/ui/           the study server and the static shell
synthtwin/cli.py        build / baseline / score
tools/merge_readings.py two blinded readings -> gold case
```
