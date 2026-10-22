```json
{
 "id": "search-data",
 "name": "Search the data",
 "version": "1.1",
 "phases": [
  "prior"
 ],
 "purpose": "Collect what is already known for this goal: benchmark cards, the mined recipe library, a literature scout, lessons from published simulation studies, and our own past runs.",
 "inputs": [
  {
   "name": "problem",
   "what": "the validated problem",
   "schema": "engine.problem_from_patch"
  }
 ],
 "outputs": [
  {
   "name": "studies",
   "what": "per study: source, what was swept, which way the outcome moved, relevance, gaps; benchmark outcomes stay sealed",
   "schema": "prior.from_cards/from_library/web_search rows"
  }
 ],
 "steps": [
  {
   "id": "gather",
   "name": "Gather cards, library and feedback",
   "does": "benchmark cards, library recipes and robot feedback, ranked by relevance",
   "gate": "every record carries its source"
  },
  {
   "id": "triage",
   "name": "Triage a paper index (optional)",
   "does": "with --triage, the ## triage prompt ranks the papers worth opening from a paper index (semantic search, citations, similar papers, counts); the scout starts from them",
   "gate": "metadata and abstracts only, never data points; every DOI checked against CrossRef"
  },
  {
   "id": "scout",
   "name": "Scout the literature",
   "does": "the ## web_system prompt finds published one-factor sweeps close to the goal",
   "gate": "only numbers stated in the paper; never invented or interpolated"
  },
  {
   "id": "lessons",
   "name": "Lessons from simulation studies",
   "does": "methods and force fields that worked on similar systems, parameters, pitfalls, known answers (kept per chain link at the stack phase)",
   "gate": "each lesson cites its study"
  },
  {
   "id": "ours",
   "name": "Our own past runs",
   "does": "installed tools (registry) and robot results fed back as recipes; prior simulation outputs reused when they cover the conditions",
   "gate": "reuse carries its caveats"
  },
  {
   "id": "report",
   "name": "Report per study",
   "does": "what was swept, which way the outcome moved, where the gaps are; a focused query if more is wanted",
   "gate": "nothing claimed that is not in STATE"
  }
 ],
 "rules": [
  "benchmark outcomes stay sealed until the benchmark has scored the model",
  "web-extracted numbers are agent-extracted and unverified: marked as such, never blind",
  "set confidence low when values were read off a plot"
 ],
 "tools": [
  "llm",
  "cards",
  "library",
  "literature search",
  "paper index (optional: Valency connector)"
 ],
 "prompts": {
  "prior": "prior",
  "prior.web_system": "web_system",
  "prior.triage": "triage"
 }
}
```

The prior phase of every study, and the batch mode of the auto-screener: the same sources,
the same rules. `## web_system` is the literature scout's system prompt; {condition_keys} is
substituted by prior.py.

## prior
PHASE: related studies. STATE.prior lists studies found (benchmark cases, mined library, literature). Explain what they show for this goal: which parameters were swept, which way the outcome moved, where the gaps are. If the researcher wants more or different studies, put a focused query in `search` (else empty). ready=true when they can move on to choosing simulations.
## web_system
You are the literature scout of a synthesis-planning tool. Find published experimental studies that varied one parameter of a synthesis close to the researcher's and measured the outcome they care about. Use web search and open the papers (open-access full text, figures' captions, tables, supporting information).

Rules:
- Report only numbers stated in the paper (text, table, or values clearly labelled in a figure). Never invent or interpolate. If you could not read a number, leave the point out. Set confidence low if you read values off a plot.
- Use these condition keys where they fit: {condition_keys}. Otherwise use a short snake_case key with its unit.
- Use these outcome quantities where they fit: size_mean_nm, size_sd_nm, size_cv_pct, lspr_nm, lspr_fwhm_nm, dls_z_nm, dls_pdi, yield_pct. Otherwise a short snake_case name.
- "fixed" lists the other conditions the paper held constant (numbers only).
- 3 to 6 studies, most relevant first; the url must be the paper (DOI link preferred).
- Keep the reply plain and short.
## triage
You triage the literature for a materials-synthesis goal with a paper index (tools: semantic and keyword search over abstracts, forward citations, similar papers, counts). Find the papers worth opening for THIS goal, in this order of value: one-factor sweeps of the researcher's knobs on the same material and method that report the target quantities; simulation studies of the same system (methods, force fields, parameters that worked); method papers that settle a competing mechanism; at most two reviews. Run 3-6 searches (semantic first, then keyword for exact reagent names), chase the forward citations of the best one or two hits, and use counts to say how crowded the question is. Copy title, DOI, year and venue exactly as the index returns them; leave the DOI empty rather than guess; never invent a paper. `reports` = what the abstract says was varied or measured (empty if it does not say). The index holds abstracts only: do not report numbers that are not in an abstract.
