```json
{
 "id": "design",
 "name": "Design the case and the recipe",
 "version": "1.0",
 "phases": [
  "case",
  "recipe"
 ],
 "purpose": "Map the researcher's own case, propose candidates with honest bands, and write the recipe a person approves.",
 "inputs": [
  {
   "name": "problem",
   "what": "their knobs and targets"
  },
  {
   "name": "basis",
   "what": "the benchmark's chosen variant and calibration, labelled validated or exploratory"
  }
 ],
 "outputs": [
  {
   "name": "proposals",
   "what": "steps, conditions, predicted band, label, novelty, checks, risks"
  },
  {
   "name": "recipe",
   "what": "the pick, written up for a lab: why, steps, expected band, checks, risks, alternatives"
  }
 ],
 "steps": [
  {
   "id": "sensitivities",
   "name": "Sensitivities and maps",
   "does": "a tornado of each knob's effect on each target; 2-D maps over knob pairs",
   "gate": "insights cite the map, not vibes"
  },
  {
   "id": "bounds",
   "name": "Search physical bounds",
   "does": "solubility, boiling point, reagent stability, the vessel: not only the validated region",
   "gate": "no proposal outside physics"
  },
  {
   "id": "mix",
   "name": "Exploit and explore",
   "does": "about 60% of proposals inside the validated region, 40% extrapolations to physical bounds, each labelled",
   "gate": "extrapolations carry wider bands and are labelled"
  },
  {
   "id": "novelty",
   "name": "Novelty check",
   "does": "a candidate within tolerance of a known recipe is dropped; thin coverage reported as thin",
   "gate": "no proposal goes out without it"
  },
  {
   "id": "write",
   "name": "Write the recipe",
   "does": "numbered steps with volumes and temperatures, expected outcome with band, quick checks on the robot, risks, alternatives in one line",
   "gate": "never present a recipe that misses the target as if it hit it"
  },
  {
   "id": "approve",
   "name": "Human approval",
   "does": "a person approves before anything runs; robot-limit drops and their fixes said plainly",
   "gate": "the approval is recorded"
  }
 ],
 "rules": [
  "every number comes from the library, the simulator (with band) or a stated assumption",
  "each proposal is labelled inside validated region or extrapolation",
  "steps needing a capability the robot does not list are named, not filtered"
 ],
 "tools": [
  "llm",
  "predictor",
  "optimiser",
  "novelty check"
 ],
 "prompts": {
  "case": "case",
  "recipe": "recipe"
 }
}
```

A6/A7. The case phase simulates and maps; the recipe phase writes it up. The 60/40
exploit/explore mix with labels is the target behaviour (see docs/PIPELINE.md for what is
built today).

## case
PHASE: the researcher's case was simulated. STATE.case has the sensitivities (tornado), the 2-D map summary, and the optimiser's proposals with predicted bands. Give 3-5 insights (which knob matters most and which way, where the target region is, what the uncertainty is). If they ask for different knob ranges, return them in `knobs` (else empty) and the case is re-run.
## recipe
PHASE: recipe. From STATE.case.proposals pick the recipe to run first (`choice` = its id) and write it up for a lab: a title, why this one, numbered steps with volumes and temperatures from the proposal, the expected outcome with its band, quick checks on the robot (UV-Vis/DLS values that confirm success), and risks. Mention the alternatives in one line. If STATE.case.dropped holds candidates closer to the target that were dropped for robot limits (e.g. a dispense volume below the minimum), say so plainly in `reply` and in the recipe's `alternatives`, with the concrete fix (a more dilute stock, a larger batch) and what it would gain; never present a recipe that misses the target as if it hit it. ready=true when the researcher can send it to the robot.
