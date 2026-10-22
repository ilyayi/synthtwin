```json
{
 "id": "validate",
 "name": "Validate the stack",
 "version": "1.0",
 "phases": [
  "sample",
  "bench"
 ],
 "purpose": "Choose the benchmark sample blind, score the stack against the null floor, ablate every method, and say plainly what can be trusted.",
 "inputs": [
  {
   "name": "candidates",
   "what": "related studies with data the stack could be tested on"
  },
  {
   "name": "predictions",
   "what": "the stack's predictions per study and variant"
  }
 ],
 "outputs": [
  {
   "name": "scores",
   "what": "per study and variant: Spearman, MAE, band coverage, trend_ok vs the null",
   "schema": "sweep.SweepScore"
  }
 ],
 "steps": [
  {
   "id": "sample",
   "name": "Choose the sample",
   "does": "3-7 studies closest to the case (same material and method first, swept variables that are the knobs); benchmark cases are blind",
   "gate": "selected ids from the candidates"
  },
  {
   "id": "score",
   "name": "Score against the null",
   "does": "anchor in, predict every other point; per quantity: Spearman, MAE, band coverage against the anchor-everywhere null with a +/-30% band",
   "gate": "null floor always shown next to the model"
  },
  {
   "id": "ablate",
   "name": "Ablate",
   "does": "with and without each method, with and without anchor calibration, on the same cases; a method helps only if the scores say so",
   "gate": "every model change judged on the same cases"
  },
  {
   "id": "trust",
   "name": "Decide what is trusted",
   "does": "validated = trend_ok and beats the null MAE, on at least half the studies on average; failures reported per link; else exploratory",
   "gate": "the label (validated/exploratory) travels with every prediction"
  },
  {
   "id": "qa_verdict",
   "name": "Weigh the QA audit",
   "does": "for a built simulator, say which methods passed the QA review and what the failures mean for trust",
   "gate": "no method counted as passed that the reviewer failed"
  }
 ],
 "rules": [
  "benchmark answers are never used for calibration, search or fitting",
  "gold answers are never published; synthetic examples only",
  "a link whose ablation shows no gain is reported as such, even if its numbers look plausible"
 ],
 "tools": [
  "predictor",
  "scores",
  "vault"
 ],
 "prompts": {
  "sample": "sample",
  "bench": "bench"
 }
}
```

A3/A5: the blind benchmark. The sample phase picks the studies; the bench phase scores
and explains. Blind means blind: the builder saw conditions and one anchor per study, and the
sealed points are opened only here, for scoring.

## sample
PHASE: benchmark sample. STATE.candidates are related studies with data that the stack could be tested on (benchmark cases are blind tests; literature studies are not blind). Pick 3-7 that are closest to the researcher's case (same material and method first, swept variables that are their knobs) and explain the choice. Return the chosen ids in `selected`. ready=true when the sample is settled.
## bench
PHASE: benchmark results. STATE.bench has, per study and model variant, the error vs the null (anchor-everywhere) floor and whether the trend is right. Explain plainly whether the stack can be trusted for this case, which variant to use (`variant`), and what the failures mean. For a built simulator, STATE.build.qa is the QA reviewer's audit of each method (converged? sampled enough? physical?): say which methods passed, which did not and what that means for trust. The researcher then approves running their own case (ready=true when they can).
