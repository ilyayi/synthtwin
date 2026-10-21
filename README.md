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

```
synthtwin/schemas.py    case card, vault entry, prediction and score formats
synthtwin/cards.py      gold case -> (card, vault entry); anchor = median sweep point
synthtwin/vault.py      sealed storage and leak scanning
synthtwin/score.py      scoring
synthtwin/baseline.py   null and calibrated-model predictors
synthtwin/cli.py        build / baseline / score
tools/merge_readings.py two blinded readings -> gold case
```
