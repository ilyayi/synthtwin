```json
{
 "id": "paper-index",
 "name": "Read the paper index",
 "version": "1.0",
 "phases": [
  "goal",
  "prior",
  "stack",
  "sample",
  "bench",
  "case",
  "recipe"
 ],
 "purpose": "Every step that reads papers can query a paper index (the Valency connector: semantic and keyword search over abstracts, forward citations, similar papers, counts) for leads, precedent and how crowded a question is.",
 "inputs": [
  {
   "name": "paper index",
   "what": "the connector tools named by the server's --paper-index (default valency); absent = the steps run as before"
  }
 ],
 "outputs": [
  {
   "name": "cited leads",
   "what": "titles and DOIs exactly as the index returns them, in the step's own fields (lessons, reply, precedent)"
  }
 ],
 "steps": [
  {
   "id": "goal",
   "name": "Is the target realistic?",
   "does": "counts papers on the material and method; one search for what values of the target were reached",
   "gate": "a target outside what abstracts report is flagged, with the DOI of what was reached"
  },
  {
   "id": "prior",
   "name": "Triage before the scout",
   "does": "the search-data protocol's ## triage ranks the papers to open first (prior/triage.py)",
   "gate": "every DOI checked against CrossRef"
  },
  {
   "id": "stack",
   "name": "Simulation precedent per link",
   "does": "simulation studies of the same or a close system per high-sensitivity link: method, force field, parameters, pitfalls",
   "gate": "each lesson carries its DOI; a link with no precedent is said to have none"
  },
  {
   "id": "sample",
   "name": "Check the benchmark sample",
   "does": "abstracts confirm the picked studies vary a knob and report a target; closer sweeps missing from the candidates are named",
   "gate": "missing studies are named for a literature search, never added as data"
  },
  {
   "id": "build",
   "name": "Parameter sources for the builder",
   "does": "the builder finds where a parameter was measured or computed, then opens the paper for the number",
   "gate": "abstract text is a lead, not a value; every parameter's DOI goes in NOTES.md"
  },
  {
   "id": "case",
   "name": "Precedent for the best region",
   "does": "published syntheses near the optimiser's proposals, and whether they reached the predicted outcome",
   "gate": "precedent supports a proposal; none makes it novel and riskier"
  },
  {
   "id": "recipe",
   "name": "Closest published recipe",
   "does": "the closest published recipe to the chosen proposal, and how it differs",
   "gate": "never claim novelty without having searched"
  }
 ],
 "rules": [
  "the index holds metadata and abstracts only: leads, counts and precedent, never data points",
  "titles and DOIs exactly as the index returns them; leave a DOI empty rather than guess; never invent a paper",
  "a few calls per turn, only where the answer can change the step's decision",
  "sealed benchmark outcomes stay sealed: the index is never used to look up a held-out study's results"
 ],
 "tools": [
  "paper index (Valency connector, through the claude CLI)"
 ],
 "prompts": {
  "index.rules": "rules",
  "index.goal": "goal",
  "index.stack": "stack",
  "index.sample": "sample",
  "index.build": "build",
  "index.case": "case",
  "index.recipe": "recipe"
 }
}
```

One paper index for the whole pipeline. The server names it (`--paper-index valency`, the
default; `none` turns it off). The prior step's triage has its own prompt in the search-data
protocol; every other step's agent turn gets `## rules` plus its own section below, with the
connector tools allowed for that call. The builder of the bench step gets `## build` appended
to its brief. With no index, every prompt is byte-identical to before.

## rules
PAPER INDEX: this turn may query a paper index (tools listed at the end). It holds metadata and abstracts only: use it for leads, counts and precedent, never as a source of data points. Copy titles and DOIs exactly as the index returns them; leave a DOI empty rather than guess; never invent a paper. Make a few calls at most, only where the answer can change this step's decision, and never use it to look up the results of a held-out benchmark study.
## goal
Before settling the targets, check them against what was published: count papers on this material and method, and run one semantic search for the target property. If a target lies outside what the abstracts report, say so in `reply`, with what was reached instead and its DOI.
## stack
For each high-sensitivity link of the chain, search for simulation studies of the same or a close system (method, force field or functional, parameters that worked, pitfalls, known answers to reproduce) and put what you find, with its DOI, in that link's lessons. Use similar papers and forward citations of the best hit to reach newer work. Say so when a link has no simulation precedent.
## sample
For the candidates you pick, check from the abstract that they vary one of the researcher's knobs and report a target quantity. If the index shows a closer sweep that is missing from STATE.candidates, name it (title, DOI) in `reply` so the researcher can fetch it with a sharper literature search; never add it to the sample yourself.
## build
## Paper index
You can query a paper index (tools listed below): semantic and keyword search over abstracts, forward citations, similar papers. Use it to find where a parameter you need (a rate constant, surface energy, binding energy, force field, diffusion coefficient) was measured or computed, then open that paper with WebFetch for the number. Abstract text is a lead, not a value: record every parameter's source (DOI) in NOTES.md. Never look up the results of the held-out benchmark studies.
## case
Check whether the optimiser's best region has precedent: search for published syntheses near the proposed conditions and say in one insight whether they reached what the simulator predicts there. Precedent supports a proposal; none makes it novel and riskier: say which.
## recipe
Before writing the recipe, search for the closest published recipe to the chosen proposal. In `reply`, state the precedent (title, DOI, how it differs from this recipe) or that none was found, so the recipe is novel; never claim novelty without having searched.
