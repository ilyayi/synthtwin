```json
{
 "id": "find-simulations",
 "name": "Find the simulations for a system",
 "version": "1.1",
 "phases": [
  "stack"
 ],
 "purpose": "Design the simulation stack: a chain of links from the researcher's knobs to their targets, with methods per link chosen by scale and by the information they add for the decision.",
 "inputs": [
  {
   "name": "problem",
   "what": "the validated problem"
  },
  {
   "name": "related studies",
   "what": "the prior phase's studies and lessons"
  }
 ],
 "outputs": [
  {
   "name": "chain",
   "what": "the links with physics, inputs/outputs, sensitivity, data, competing mechanisms, lessons",
   "schema": "engine.CHAIN_LINK"
  },
  {
   "name": "methods",
   "what": "per link: id, scale, tool, role, feeds, check, est_min, selected, insight",
   "schema": "engine.GENERIC_METHOD or the catalog ids"
  },
  {
   "name": "scales",
   "what": "the same stack at three scales (reactor / molecular / atomistic): processes with formulas and icons, size, time, what passes down",
   "schema": "engine.SCALE_ITEM"
  }
 ],
 "steps": [
  {
   "id": "chain",
   "name": "Split the synthesis into links",
   "does": "the links that carry the knobs to the targets, with a vessel/process link feeding the rates (3-9 links)",
   "gate": "every target reachable from every knob"
  },
  {
   "id": "per_link",
   "name": "Analyse each link",
   "does": "governing physics, parameters, sensitivity of the targets (high/medium/low, with the reason), constraining data, competing mechanisms, lessons from similar simulation studies",
   "gate": "spend effort where sensitivity is high and data are thin"
  },
  {
   "id": "scales",
   "name": "Cover the three scales",
   "does": "reactor (the vessel and process conditions), molecular (what the conditions do to molecules and particles in the liquid), atomistic (interactions between atoms); couple them through fitted surrogates",
   "gate": "each scale named per link where it matters"
  },
  {
   "id": "methods",
   "name": "Pick methods per link",
   "does": "from the catalogue, the tool area and the literature, by scale; each with its check and an honest est_min",
   "gate": "a method is picked by the information it adds for this decision, not by cost"
  },
  {
   "id": "select",
   "name": "Select and estimate",
   "does": "selected or not with the one-line insight; the total estimate; queued/planned methods only when essential and said what they cost",
   "gate": "at least one method selected"
  },
  {
   "id": "gaps",
   "name": "Name the gaps",
   "does": "a link no method serves is a gap: say so",
   "gate": "gaps explicit, not silent"
  }
 ],
 "rules": [
  "every number has a source: library, simulator band, or stated assumption",
  "every method is audited by a QA reviewer after it runs",
  "a method feeds the predictor only through its declared outputs"
 ],
 "tools": [
  "llm",
  "catalog",
  "toolbox",
  "literature search"
 ],
 "prompts": {
  "stack": "prompt",
  "stack_other": "prompt_other"
 }
}
```

The core protocol. `## prompt` serves systems with a built-in simulator (the method
catalogue); `## prompt_other` serves systems the platform builds a simulator for (STATE.tools,
the chain-first design, {budget} and {install} substituted by the engine). The three scales
every study presents, each with its own visual (see the visualize protocol):

- **reactor** — the vessel and the process conditions: heating, mixing, dosing, evaporation, flow;
  what conditions the liquid actually sees.
- **molecular** — what those conditions do to the molecules and particles in the liquid:
  speciation, reaction, nucleation, growth, aggregation.
- **atomistic** — interactions between atoms: bonding, surfaces, ligands, coalescence.

## prompt
PHASE: simulation stack. STATE.catalog lists the methods with status (runnable, cached, literature, queued = would run for hours/days on the GPU pool, planned = not built), time estimates and when each helps. Choose the stack for THIS goal: for each method say selected or not and, in one line, the insight it would give here (or why not). Prefer what changes the decision; do not select queued/planned methods unless the researcher asks or they are essential, and then say what that costs. Also return the CHAIN this stack implements in `chain`: the links from the knobs to the targets (e.g. recipe -> solution chemistry -> reduction kinetics -> nucleation -> growth/ripening/aggregation -> structure -> optics/readout, with the vessel feeding the rates), and per link its physics, inputs, outputs, sensitivity (high/medium/low and why), what data constrain it, competing mechanisms, lessons from simulation studies of similar systems, and the catalog method ids that serve it (a link no catalog method serves is a gap: say so). Also return `scales`: the same stack at three scales, all three present even when no method is selected there (then say what is assumed and which method would cover it). reactor = the vessel and process (heating, stirring, dosing, evaporation, flow, residence time) and the conditions it creates; molecular = what those conditions do to the molecules and particles in the liquid (speciation, kinetics, nucleation, growth, ripening, the product's optics); atomistic = the interactions between atoms (bonding, surface/binding energies, ligand binding, coalescence by MD, DFT). 2-4 processes per scale, each with a name, one line on what it does, one honest formula (plain text: `_x`/`_{xy}` subscript, `^x`/`^{xy}` superscript) and an icon from the enum, plus size, time, what it passes down to the next scale, and the link/method ids it covers. Return all methods in `methods`. ready=true when the stack is settled.
## prompt_other
PHASE: simulation stack for a system without a built-in simulator. STATE.tools lists the engines on this machine. Design the stack as a CHAIN, in this order:
1. Chain. Split the synthesis into the links that carry the researcher's knobs to their targets, e.g. recipe -> solution chemistry -> reaction kinetics -> nucleation -> growth/ripening/aggregation -> structure -> property -> instrument readout, with a vessel/process link (heat, mixing, evaporation, flow) feeding the rates. Use as many links as the system needs (3-9), each with its inputs and outputs, so every target is reached from every knob.
2. Per link: the governing physics, the parameters it needs, how sensitive the targets are to it (high/medium/low, with the reason: spend effort where sensitivity is high and data are thin), what data already constrain it, competing mechanisms the benchmark should decide between, and lessons from simulation studies of similar systems (methods and force fields that worked, parameters, pitfalls, known answers to reproduce).
3. Methods per link, chosen by scale: electronic (DFT/xTB: binding, reaction, formation energies, NEB barriers), atomistic (classical MD: diffusivities, Tg, densities, interaction energies, viscosity; ReaxFF or ML potentials where bonds form or break), mesoscale (kMC, phase-field, population balance), continuum (transport/FEM/CFD in Python), reactor/process (microkinetics as in Cantera/OpenMKM, CFD+population balance as in OpenFOAM+OpenQBMM; couple scales through a fitted surrogate the next scale calls), readout (the instrument model that turns the structure into what is measured), and data (fits to the related studies, a residual model). Pick by the information each adds for THIS decision, not by cost. Each method gets id (snake_case), name, link (the link id), scale, tool (from STATE.tools), role (what it computes here), feeds (which model parameter or quantity it supplies), check (the known answer or convergence test that gates it), est_min (honest wall minutes on this machine, including convergence tests and enough sampling) and selected; insight = one line on what it tells the researcher. Also return `scales`: the same stack at three scales, all three present even when no method is selected there (then say what is assumed and which method would cover it). reactor = the vessel and process (heating, stirring, dosing, evaporation, flow, residence time) and the conditions it creates; molecular = what those conditions do to the molecules and particles in the liquid (speciation, kinetics, nucleation, growth, ripening, the product's optics); atomistic = the interactions between atoms (bonding, surface/binding energies, ligand binding, coalescence by MD, DFT). 2-4 processes per scale, each with a name, one line on what it does, one honest formula (plain text: `_x`/`_{xy}` subscript, `^x`/`^{xy}` superscript) and an icon from the enum, plus size, time, what it passes down to the next scale, and the link/method ids it covers. {budget} {install} Every method is audited by a QA reviewer agent after it runs. Return the links in `chain` and all methods in `methods`. ready=true when the stack is settled.
