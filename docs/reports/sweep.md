# Branch `sweep`: general benchmark (synthtwin/sweep.py + CLI)

Generalises the CO light-off benchmark to any conditions -> outcomes sweep
(`SweepCase` / `SweepVault` / `SweepPrediction` / `SweepScore` in the frozen
`schemas.py`). The CO modules (`cards.py`, `vault.py`, `score.py`,
`baseline.py`) keep their behaviour; all 36 pre-existing tests pass unchanged.

## What was built

- `synthtwin/sweep.py` (239 lines)
  - `split_sweep_gold(gold, existing_canary=None) -> (SweepCase, SweepVault)`:
    gold JSON = SweepCase fields minus `anchor_*`, plus `measured: {label:
    [Outcome]}` and `digitised_by`. Anchor = median swept value (lower median
    for even n, label breaks ties) - deterministic; the card carries only the
    anchor's outcomes; canary stable across rebuilds (as in `cards.py`).
  - `leak_scan(paths, canary, values)` + `held_out_values(vault, anchor_label)`:
    flags the canary or 3+ held-out values pooled over all quantities, each to
    1 decimal or as an integer (no K/degC shift - units are nm, %, ...).
  - `score_sweep(case, vault, pred) -> list[SweepScore]`, one per quantity in
    `case.quantities`: spearman over all points (None if n < 3 or constant),
    mae and band coverage over non-anchor points, `trend_ok` = spearman >= 0.8
    for n >= 4 else exact rank order; a skipped point/quantity makes the score
    incomplete -> `trend_ok` False and the point counts as a coverage miss.
  - `null_predict` (anchor outcomes everywhere, band +-30 % relative) and
    `model_predict(case, predict, calibrate)`: `calibrate(anchor conditions,
    {quantity: value})` on the anchor, then `predict({**point.conditions,
    **calibrated})` per point. `load_sweep_model("pkg.mod:fn")` resolves a
    class/factory with `.predict` / `.calibrate`.
- `synthtwin/vault.py`: new generic `write_sealed` / `read_sealed` (dir 700 /
  file 600 for any vault schema); `write_vault` / `read_vault` delegate,
  behaviour unchanged.
- `synthtwin/cli.py`: `synthtwin.cli sweep build <gold> <cards> <vault>`,
  `sweep baseline --predictor null|model [--model pkg.mod:fn]`,
  `sweep score <cards> <vault> <predictions>` -> `sweep_scores.jsonl` +
  `sweep_scores.md` (markdown table, one row per case x quantity, printed).
  CO commands and table untouched.
- `examples/sweep_gold/`: 3 synthetic NP cases (made-up numbers): Au size/cv
  vs citrate ratio (5 pts), Au size/LSpr vs pH (4 pts), Ag size/DLS vs seed
  ratio (3 pts).
- README: "General sweeps" section (usage + simulator contract).

## Tests

74 pass (36 pre-existing + 38 new), pytest, no network:
`tests/test_sweep_{split,vault,score,baseline,cli}.py` + `tests/stub_np_model.py`.
Hand-computed scores: case np-au-citrate-a null predictor - size mae 12.25,
coverage 0.00; cv mae 5.25, coverage 0.75; spearman None (constant).
Permissions: vault dir 700 / file 600 asserted. Leak scan: canary, 3 values
across quantities, integer forms, neighbouring-number guards.

## Numbers (synthetic examples - no real NP data exists in this repo)

null predictor, `examples/sweep_gold`:

| case | quantity | spearman | mae | coverage | trend_ok |
|---|---|---|---|---|---|
| np-au-citrate-a | size_mean_nm | - | 12.25 | 0.00 | False |
| np-au-citrate-a | size_cv_pct | - | 5.25 | 0.75 | False |
| np-au-ph-b | size_mean_nm | - | 16.5 | 0.00 | False |
| np-au-ph-b | lspr_nm | - | 6.33 | 1.00 | False |
| np-ag-seed-c | size_mean_nm | - | 11.5 | 0.50 | False |
| np-ag-seed-c | dls_z_nm | - | 13 | 0.50 | False |

stub model (size = scale * 30 * ratio^-0.7, calibrated on the anchor):
np-au-citrate-a size_mean_nm spearman 1.00, mae 4.47, coverage 0.50,
trend_ok True; every quantity the stub does not predict scores incomplete
(trend_ok False, coverage 0). The +-30 % null band is generous for
large-valued quantities (lspr coverage 1.00) - expected.

## Known gaps

- No real nanoparticle gold cases yet (none exist in this repo); the digitiser
  merge tool (`tools/merge_readings.py`) is CO-specific - a SweepOutcome
  merger is future work when real NP readings arrive.
- The leak scan pools values across quantities (3 values of any quantity is a
  leak); it cannot catch a single leaked value, same as the CO scan.
- `model_predict` passes only `point.conditions` (plus calibrated params) to
  the simulator - material/method are on the card but not in the params dict;
  a real simulator that needs them should read them from its calibration or
  we extend the contract later.
- Integer-form leak matching can hit incidental numbers (dates, ratios) in
  agent prose; threshold 3 keeps false positives rare but not impossible.
