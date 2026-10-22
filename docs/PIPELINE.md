# SynthTwin pipeline

SynthTwin turns a synthesis problem into experiments a robotic lab can run. It works like a
research student: it agrees a measurable goal, reads what was done before, designs and builds the
simulations that the decision needs, tests them blind on published results, and only then proposes
recipes. Every number it reports comes from the literature, from a simulator that has been checked
against held-out published results, or from a stated assumption.

Part A is the general pipeline. Its core is the **simulation stack** (A4). Part B applies it to
colloidal Au/Ag nanoparticle (NP) synthesis. Each feature is marked **built**, **partial** or
**planned**.

```
A0 Intake ─ manual problem (default) | auto-screener over the recipe library (option)
   │
A1 Problem ── goal, targets, knobs, fixed conditions; validated before anything runs
   │
A2 Prior ──── recipe library + literature + lessons from published simulation studies + our own past runs
   │
A4 Stack ──── chain of links → methods per link, by scale → contracts and gates      (the core)
   │
A3/A5 ─────── blind benchmark sample → builder agent runs the stack → QA review → blind score + ablation
   │
A6 Case ───── sensitivities, 2-D maps, optimiser: exploit inside the validated region, explore to physical bounds
   │
A7 Recipe ─── a person approves; steps, expected band, checks, risks
   │
A8 Robot ──── protocol package to a self-building lab → measurements and run logs come back
   │
A9 Feedback ─ results join the library; robot sweeps become new held-out benchmark cases
```

## The flow in short

1. The researcher states the problem in chat. The agent turns it into targets, knobs and fixed
   conditions, and asks only what it needs. (Or the auto-screener proposes the problem: A0.)
2. The agent collects related studies: the mined recipe library, the blind benchmark cards and a
   literature search. It says what each study swept and what moved.
3. The agent designs the simulation stack as a chain from the knobs to the targets. For each link
   it says how much the targets depend on it, what data constrain it, which mechanisms compete,
   what similar simulation studies learned, and which methods (from DFT to reactor models) serve
   it.
4. The researcher ticks the methods and picks the benchmark studies.
5. A builder agent carries out the stack on the local machines and assembles a fast predictor.
   A QA reviewer agent audits every method.
6. The predictor is scored blind on the held-out studies, against a null predictor.
7. The case phase maps the researcher's knobs. The optimiser proposes candidates, both inside
   the validated region and beyond it, up to physical bounds.
8. The agent writes the recipe and a person approves it. The protocol goes to a self-building
   lab, and the results come back as library entries and new benchmark cases.

## Repo layout

Everything about one pipeline step lives in one folder — change a step, touch only its folder:

```
synthtwin/
  steps/<step>/        one folder per UI step, in order (goal, prior, stack, sample, bench, case, recipe, robot):
                       step.json (its registry entry: order, name, icon, strip text, protocols, gate),
                       protocol.md (its versioned protocol), schema.py (its LLM schema + cleaning),
                       run.py (its handlers), panel.js / panel.css (its UI panel)
  protocols/           the cross-cutting protocols (onboard-data, onboard-tool, visualize) + the registry
  core/                the engine orchestrator (study lifecycle, gates, dispatch), llm, schemas, runner,
                       catalog, systems, toolbox
  lib/                 the science several steps share: np/, atomistic/, recipes/, design/, screen/,
                       cards/vault/score/baseline/sweep, viz
  agent/               import shims to the pre-steps paths (synthtwin.agent.engine -> core.engine, ...)
  ui/                  server.py + the static shell (index.html, common.js, agent.js, theme/agent/screen css);
                       each step's panel.js/panel.css are served concatenated as /static/steps.js + steps.css
  cli.py               the command line
```

`steps/__init__.py` reads every step.json and exposes `STEPS` / `ORDER`; the engine's phase list, the
UI stepper and the protocol phase mapping all derive from it, so the shape of the pipeline is
declared once, by the steps themselves.

---

# Part A: the general pipeline

## A0. Intake — [onboard-problem](#protocols) · code: `synthtwin/steps/goal/`

| Mode | What the researcher does | Status |
|---|---|---|
| **Manual (default)** | Describes the problem in chat. The agent drafts the goal, the researcher corrects it and confirms. | built |
| **Auto-screener (option)** | Picks a material type and an application, and optionally a metric, a budget, and materials to include or exclude, then launches it. | planned |

The auto-screener works as follows:
- It scans the recipe library (e.g. LeMat-Synth) for records in the chosen class.
- From each record it forms a "beat the best reported X" study: the target is the best reported
  value of the metric, and the knobs are the conditions the record's family varies.
- It queues those studies and ranks them on a leaderboard by expected gain, data density and cost.
- The researcher steers it: re-rank, pin or drop studies, change the metric or the budget.
- Each queued study enters A1 like a manual one. A person still approves every robot run.

**New-material mode.** When the screener proposes compositions that are not in the library, it
attaches a **stability risk score** (e.g. energy above the convex hull from a materials database
or an ML potential). The score is a warning, not a gate:
- A metastable phase is allowed when the process can lock it in, for example by kinetic control,
  a ligand, a substrate or quenching.
- The recipe then says which step does the locking.
- For known materials there is no stability filter.

## A1. Problem — [onboard-problem](#protocols) · code: `synthtwin/steps/goal/`
**What it contains:** the material, the method, one to three targets (each equal to, at most or at
least a value), one to four knobs with ranges, and the fixed conditions.

**Protocol:**
- Every target must be measurable on the robot.
- Knob keys are canonical (`temperature_C`, `pH`, `conc_*_mM`, `ratio_*`, `time_min`, ...) for
  built-in systems. Other systems use snake_case keys that end in their unit.
- An invalid problem goes back to the agent with every error listed.

The agent never decides what the robot cannot do. A self-building lab can add a capability (A8),
so a recipe states which steps need capabilities the robot does not list yet.

## A2. Prior knowledge — [search-data](#protocols) · code: `synthtwin/steps/prior/`
| Source | What it gives | Status |
|---|---|---|
| Recipe library (LeMat-Synth dump, case cards) | `Recipe` records: reagents with roles, conditions, outcomes, source. Ranked by material, method and conditions. `novelty.check` gives the nearest known recipe. | built |
| Literature search | The agent reads papers on the same system and extracts what was swept and what moved (not verified; marked as such). | built |
| **Lessons from simulation studies** | For each chain link: the methods and force fields that worked on similar systems, parameter values, pitfalls, and known answers to reproduce as gates. The stack designer searches for them while designing (A4.2). | built (agent search); a curated store is planned |
| **Our own past results** | Software already installed and checked (tool registry). Robot results fed back as recipes. Prior simulation outputs reused instead of rerun when they cover the conditions (e.g. a pilot MD study reused for diffusivities, with its caveats). | partial: registry and feedback built; a parameter store with provenance is planned |

**Protocol:**
- Every record carries its source.
- An outcome is mined only from the same sentence as its value, with units.
- A family with fewer than 3 recipes is **thin**, and a candidate in a thin family is never called
  "novel".

## A3. Gold benchmark (blind) — [validate](#protocols) · code: `synthtwin/steps/sample/`
Published one-factor sweeps become benchmark cases (`synthtwin/lib/sweep.py`).

1. **Find papers.** Look for one varied factor, 3 or more points, a full recipe, outcomes with
   spread, and free full text.
2. **Two readers extract the data independently.** A value is kept only if both readers give it
   and they agree within the read error. A disagreement stops the build for a person to look at.
3. **Split.** Each case gets a card with one **anchor** point (the median of the swept values).
   The other points are sealed in a vault (mode 700/600, with a canary).
4. **Leak scan.** Check everything a predictor or builder can see.
5. Real gold answers are **never published or used for fitting**; this repository ships only
   synthetic examples. The builder agent sees the benchmark studies' conditions and anchor only,
   and is told not to look the papers up.

## A4. The simulation stack (the core) — [find-simulations](#protocols) · [build-and-qa](#protocols) · code: `synthtwin/steps/{stack,bench}/`
The stack is designed as a chain of links before any method is picked. It is built in nine steps.

### A4.1 Chain decomposition
- Split the synthesis into links that carry the knobs to the targets. For example: recipe →
  solution chemistry → reaction kinetics → nucleation → growth / ripening / aggregation →
  structure → property → instrument readout.
- A **vessel/process link** (heat transfer, mixing, evaporation, flow) feeds the rates of every
  other link.
- Each link is one function with named inputs and outputs, so a failing link can be found and
  swapped without rebuilding the rest.

### A4.2 Per-link analysis
For each link the stack designer records:
- **physics:** the governing equations or mechanism;
- **inputs and outputs**;
- **sensitivity:** high, medium or low, with the reason;
- **data:** what already constrains the link (library, literature, benchmark anchors);
- **competing mechanisms:** alternatives that the benchmark, not the designer, decides between;
- **lessons:** what simulation studies of similar systems found (methods and force fields that
  worked, parameters, pitfalls, known answers).

### A4.3 Method catalogue, by scale
| Scale | Methods | Typical outputs | Example tools |
|---|---|---|---|
| electronic | DFT, semi-empirical (xTB), NEB | binding, reaction and formation energies; barriers; band gaps | Quantum ESPRESSO, CP2K, xTB |
| atomistic | classical MD, reactive MD (ReaxFF), ML potentials | diffusivities, densities, Tg, viscosity, interaction and free energies, cluster energetics | LAMMPS, GROMACS, OpenMM; MACE-type universal or DeePMD-trained potentials |
| mesoscale | kinetic Monte Carlo, phase-field, population balance | nucleation and growth statistics, morphology, size distributions | written in Python; kMC codes |
| continuum | reaction–diffusion, heat and mass transport, film drying and levelling, FEM/FV | fields and profiles in the vessel or film | Python (numpy/scipy), FEniCS |
| **reactor / process** | microkinetics; CFD coupled to a population balance; process models | rates under real mixing and heating; residence-time and temperature histories; scale-up | Cantera, OpenMKM, OpenFOAM + OpenQBMM, MOOSE, IDAES |
| readout | instrument models | what the robot actually measures (UV-Vis, DLS, PL, TEM statistics, film thickness) | Mie/T-matrix optics, DLS intensity weighting |
| data | fits to related studies, residual models, surrogates | calibrated parameters, corrections, uncertainty bands | scikit-learn, GP/BO |

**Coupling between scales.** Couple scales through a fitted **surrogate**: the finer scale is run
over a design of conditions, a cheap regressor is fitted to its output, and the coarser scale
calls that regressor.
- ReaxPro is an example: DFT feeds kinetic Monte Carlo, an ML surrogate of the turnover rate is
  fitted, and reactor CFD uses it.
- We borrow the pattern, not the service. Its DFT engine is commercial and its kMC code needs
  registration.

### A4.4 Contracts
Every method declares:
- inputs and outputs, with units;
- the uncertainty it reports;
- its validity domain (the conditions it was checked on);
- its cost in wall time on this machine.

The method feeds the predictor only through its declared outputs. A method is never fitted to
benchmark answers.

### A4.5 Gates
A method's result is used only after it passes three gates:
- **Known answer:** it reproduces a published value for a reference system, e.g. a bulk density,
  a diffusivity, a lattice constant, or an LSPR peak at a known size.
- **Convergence:** results hold within tolerance under changes in cell size, time step, sampling
  length, mesh or basis set.
- **QA review:** a separate reviewer agent audits each method (converged? sampled enough?
  physical?) and sends fixes back to the builder, for up to three rounds.

### A4.6 Spend effort where sensitivity is high and data are thin
An expensive method is used for a parameter only when all three hold:
- **Sensitive:** the targets move across the parameter's plausible range. This is checked with
  the fast model first.
- **Poorly constrained:** the data cannot fit the parameter, or it is confounded with another.
- **Computable:** it gives a number with an uncertainty in GPU-hours or GPU-days, with a
  validated potential or functional.

**Decision order:**
1. A literature value, with citation.
2. Classical MD with a published potential.
3. New DFT for a key number that has no literature value.
4. ML potentials when classical potentials are known to fail.

There is no time limit on a build: long runs are chosen when they supply a parameter that matters.

### A4.7 Competing mechanisms
When a link has more than one credible mechanism (for example, classical nucleation vs
autocatalytic Finke–Watzky vs seed-mediated growth), each one is implemented as an option.
The benchmark picks between them leave-one-case-out, and the report keeps the losers.

### A4.8 Assembly
The builder agent assembles the results into `model.py`:
- a fast predictor (seconds per call) that composes the links;
- a few calibration knobs;
- a residual model for what the physics misses;
- uncertainty bands calibrated on the training studies.

Its contract is `predict(conditions) -> {quantity: {value, low, high, unit}}`, and a contract
check must pass before the benchmark runs.

### A4.9 Builder runtime and reuse
**Runtime:**
- Long jobs run detached through `simjob.py`, so they survive the agent session. When any job
  finishes, the builder resumes from its own `BRIEF.md` and `NOTES.md`.
- A GPU guard pauses local jobs above 83 °C.
- A restarted server resumes interrupted builds.

**Reuse:**
- Software the builder installs goes into one tool area, with a registry entry whose check
  command must pass. Later studies reuse what is installed.
- *Planned:* a cookbook of working inputs per method and a parameter store with provenance, so a
  number computed once is not computed again.

## A5. Validation — [validate](#protocols) · code: `synthtwin/steps/bench/`
**Scoring.** For each held-out study, the predictor gets the anchor point and then predicts every
other point. Each quantity is scored separately:

| Score | Meaning |
|---|---|
| Spearman | Rank agreement between predicted and measured values. |
| MAE | Mean absolute error on the held-out points. |
| Band coverage | Fraction of measured values that fall inside the predicted band. |
| `trend_ok` | Spearman ≥ 0.8 when n ≥ 4; otherwise the exact rank order. |

The reference is the **null** predictor: the anchor value with a ±30 % band at every point.

**Protocol:**
- A family is **validated** only when the simulator gets `trend_ok` and beats the null MAE.
- Every model change is judged by **ablation** on the same cases, with and without each method and
  with and without anchor calibration. A method "helps" only if the scores say so.
- A link whose ablation shows no gain is reported as such, even if its numbers look plausible.

## A6. Case and design — [design](#protocols) · code: `synthtwin/steps/case/`
1. **Sensitivities and maps.** A tornado chart of each knob's effect on each target, and 2-D maps
   of the target over pairs of knobs.
2. **Bounds.** The optimiser searches within **physical bounds** (solubility, boiling point,
   stability of the reagents, the vessel), not only within the validated region.
3. **Exploit and explore** (built).
   - Each returned candidate gets a label from the 60/40 batch policy (`lib/design/policy.pick`):
     **exploit** = best predicted score (kept spread out in knob space), **explore** = widest
     predicted band, where a measurement teaches the model most. The explore share defaults to
     40 % and is configurable (`optimize.run(..., explore=...)`).
   - The labels travel with the proposals (`policy` field) and show as pills on the case and
     recipe panels.
   - The 60/40 mix was chosen by benchmarking the policy on five literature optimisation
     campaigns pool-based, exactly as Liang et al. 2021 (npj Comput Mater 7:188; data MIT,
     PV-Lab/Benchmarking) benchmark Bayesian optimisation: `lib/design/bench6040.py`, results in
     `lib/design/data/bench6040.json`, summarised in the "Why 60/40" card of the case panel
     (/api/bench6040). Explore candidates carry wider bands. Their result is valuable either way:
     it extends the model's reach or exposes a failing link.
4. **Novelty.** A candidate within tolerance of a known recipe is dropped.
5. **Proposals.** Each proposal gives steps, stocks, volumes, heating, addition rate and ageing,
   the expected outcome with its band, quick checks, controls (the nearest known recipe and a
   repeat) and risks (every default assumed).

## A7. Human approval — [design](#protocols) · code: `synthtwin/steps/recipe/`
A person approves every experiment. The report gives:
- the sources;
- the calibration status;
- the label for each proposal (validated or extrapolation);
- the nearest known recipe;
- every assumption.

## A8. Robot: hand-off to a self-building lab — [handoff](#protocols) · code: `synthtwin/steps/robot/`
The approved recipe becomes a **protocol package**: steps, stocks, plate or vessel format,
measurements, expected values with bands, and the acceptance checks.

A self-building lab (e.g. Self-Building Labs, Matter Lab, University of Toronto) takes it from
there:
- It checks the steps against its capabilities.
- It builds any capability it lacks: first in its digital twin, where it simulates the step, and
  then as an approved physical trial. It saves the new capability as a reusable skill.
- It runs the protocol.

Its published demonstration was aqueous CdS quantum-dot synthesis in a 96-well plate:
19 robotic stages, 8 h at 60 °C, read out by fluorescence. What comes back to SynthTwin is the
measurements and the run logs. The robot's current capability list therefore does not filter
recipes; it only flags which steps need a new capability.

Status: built as a request with this hand-off; a formal package schema is planned.

## A9. Feedback — [handoff](#protocols) · code: `synthtwin/steps/robot/`
Measured results return in two ways:
- **As recipes** in the library, with the robot run as the source.
- **As new benchmark cases**, when they form a sweep. The robot's own sweeps become held-out tests
  for the next model version.

A failed prediction points to the link to fix, because the chain keeps each link's intermediate
outputs.

## Protocols

Every phase prompt, builder/QA instruction and tool policy in the platform is a versioned protocol
file (Markdown: a ```json metadata block, then the prompt sections the
engine reads verbatim): cross-cutting ones in `synthtwin/protocols/`, the rest in the step folder
they run in (`synthtwin/steps/<step>/protocol.md`). `python -m synthtwin.protocols --check` validates the set; each study
records the versions it ran under (`protocols` in its JSON), and `/api/agent` lists the manifest.

| id | stage | what it guarantees | file |
|---|---|---|---|
| onboard-problem | A0–A1 | a validated problem (targets, knobs, fixed conditions) before anything runs | `synthtwin/steps/goal/protocol.md` |
| onboard-data | off-phase | a new data source enters the index with provenance, dedupe and a smoke check | `synthtwin/protocols/onboard-data.md` |
| onboard-tool | off-phase | a new engine is installed, gated by a known answer and listed in the catalogue | `synthtwin/protocols/onboard-tool.md` |
| search-data | A2 | what is already known: library, benchmark cards, literature scout, past runs | `synthtwin/steps/prior/protocol.md` |
| find-simulations | A4.1–A4.7 | a chain of links with methods per scale, picked by information for the decision | `synthtwin/steps/stack/protocol.md` |
| build-and-qa | A4.8–A4.9 | the builder runs the stack under contracts; a QA reviewer audits every method | `synthtwin/steps/bench/protocol.md` |
| validate | A3, A5 | a blind sample, a score against the null floor, ablation, a plain trust verdict | `synthtwin/steps/sample/protocol.md` |
| visualize | off-phase | one honest visual per scale, from simulation output or the exact model input | `synthtwin/protocols/visualize.md` |
| design | A6–A7 | sensitivities, maps, 60/40 exploit/explore, novelty check, human approval | `synthtwin/steps/case/protocol.md` |
| handoff | A8–A9 | a protocol package for a self-building lab; results feed the library | `synthtwin/steps/robot/protocol.md` |

## Rules (all stages)
- Every reported number comes from the library (with source), the simulator (with band) or a
  stated assumption.
- No proposal goes out without a novelty check. Thin coverage is reported as "thin".
- Benchmark answers are never used for calibration, search or fitting.
- A person approves every experiment.
- Extrapolations are labelled as such and carry wider bands.

## Feature status
| # | Feature | Status |
|---|---|---|
| 1 | Chat intake: the agent drafts the goal, the researcher confirms | built |
| 2 | Auto-screener with steering and a leaderboard | planned |
| 3 | Recipe library with novelty check | built |
| 4 | Literature search per study | built |
| 5 | Lessons from simulation studies, per chain link | built (agent search) |
| 6 | Reuse of our own past results (tool registry, feedback, prior runs) | partial |
| 7 | Chain-based stack design: links, sensitivity, competing mechanisms, methods by scale | built |
| 8 | Reactor/process layer (microkinetics, CFD + population balance) | in catalogue; installed on demand |
| 9 | Builder agent: no time limit, detached jobs, resumable, GPU guard | built |
| 10 | Tool area: installs with checks and a registry | built |
| 11 | QA reviewer rounds per method | built |
| 12 | Blind benchmark against null, with ablation | built |
| 13 | Sensitivities, maps, optimiser | built |
| 14 | Physical bounds with a 60/40 exploit/explore mix and labels | built |
| 15 | Stability risk score (new-material mode only, never a gate) | planned |
| 16 | Recipe with checks and risks; human approval | built |
| 17 | Protocol package for a self-building lab | partial |
| 18 | Feedback: results as recipes and new benchmark cases | partial |

---

# Part B: case study, Au/Ag nanoparticle synthesis

**Inputs** are the reaction conditions: precursor, reductant, capping agent, their ratios and
concentrations, temperature, pH or base, seed loading, number of injections, and time.

**Outputs** are the particle size mean and spread, the UV-Vis plasmon peak (LSPR), and the DLS
z-average and PDI.

## B1. Problem
Example: citrate-reduced Au (Turkevich type) at 15 nm with a size CV under 10 %. The knobs are the
citrate:Au ratio, the temperature and the pH.

## B2. Data
- **Library:** 260 recipes from the LeMat-Synth dump, 68 of them Au/Ag. Only 11 report a size.
  Too thin to calibrate on alone.
- **Benchmark:** 7 one-factor sweeps from 4 open papers:
  - Piella et al. 2016: seeded growth, pH, tannic acid;
  - Li et al. 2011: precursor concentration, NaOH;
  - La Spina et al. 2020: Ag with tannic acid;
  - Dong et al. 2020: temperature.
- **Extraction:** two blinded readers agreed on all shared values.
- **Caveats:**
  - The seeded-growth samples come from one continuing batch, so they are correlated.
  - Dong's sizes are UV-Vis estimates, not TEM.
  - Li's NaOH sizes come from histograms.

## B3. The chain and the simulations chosen
| # | Link | Physics | Method(s) chosen | Scale | Gate | What it contributes |
|---|---|---|---|---|---|---|
| 1 | Solution chemistry | Au(III) chloro-hydroxo speciation against pH, Cl⁻ and T; citrate and tannic-acid protonation; Ag complexes | equilibrium speciation solver with literature constants | data/continuum | reproduces published speciation diagrams | Which gold species is present, and so how reactive the solution is. This is where pH enters. |
| 2 | Reduction kinetics | rate per species and reductant | literature rate laws (Ji 2007; Wuithschick 2015), plus relative barriers from xTB/DFT | electronic + data | reproduces published reduction times at reference conditions | The monomer supply rate against pH, T and ratio. |
| 3 | **Nucleation** | how many nuclei form | competing models: classical nucleation with size-dependent surface energy; Finke–Watzky autocatalysis; seed-mediated (Wuithschick). Picked leave-one-case-out. | mesoscale | known Turkevich ratio trend (Frens) | **The number of particles, which sets the final size.** This is the weakest link today. |
| 4 | Cluster thermodynamics | excess energy of small clusters | EAM MD (done); MLIP check for clusters under 2 nm | atomistic | bulk cohesive energy and surface energy | Surface energy against size, for nucleation and ripening. |
| 5 | Ligand binding | citrate, tannic acid, OH⁻, Cl⁻ on Au against charge state | explicit-water MD with an interface force field, umbrella sampling | atomistic | published adsorption free energies | Capping coverage, which slows growth and sets surface charge. This is where the pH effect on growth enters. |
| 6 | Growth and ripening | population balance with Gibbs–Thomson growth | built; add mixing time and the temperature ramp | mesoscale | mass balance; seeded growth d ∝ (1 + P/S)^(1/3) | Size mean and spread over time. |
| 7 | Aggregation | DLVO + Fuchs stability; coalescence of small pairs | surface charge from link 5; EAM dimer MD as an upper bound | mesoscale + atomistic | known stability against ionic strength | Spread and tails; failure at high pH or salt. |
| 8 | Vessel | heat-up, mixing, evaporation | lumped thermal and mixing model: round-bottom flask vs 96-well plate | reactor | measured heat-up curves | Real temperature and mixing histories feed every rate. Needed for a robot plate. |
| 9 | Readouts | what the instruments see | Mie optics (fixed and validated against published LSPR against size); DLS intensity weighting; TEM detection cutoff; Haiss estimator for UV-Vis sizes | readout | LSPR of 5–80 nm Au within ±2 nm of published values | Compares like with like: TEM vs DLS vs UV-Vis sizes. |
| 10 | Calibration | 2–3 knobs, residual model, conformal bands | fitted on training studies only | data | band coverage near nominal on held-out studies | Honest uncertainty bands for the robot. |

## B4. Where the chain stands
- **Growth (link 6) works.** On the seeded-growth and concentration series the predicted size
  follows the measured trend and beats the null predictor.
- **Nucleation (link 3) fails.** Trends against temperature, pH and NaOH come out flat or
  reversed. The model sets the number of nuclei wrongly when chemistry, rather than seeds, sets
  them.
- **Optics (link 9) has a bug.** The predicted LSPR falls as size grows from 3.5 to 20 nm, while
  real gold is flat to slightly rising. The suspected cause is the fixed 1 nm high-index ligand
  shell dominating small particles.

## B5. Fix plan, in order
1. Fix the optics and match each readout to its instrument (about 1.5 days).
2. Speciation and per-species kinetics (about 3 days).
3. Competing nucleation models, selected leave-one-case-out (about 3 days).
4. Ligand-binding MD (about 4 GPU-days, in the background).
5. Grow the benchmark from 7 to more than 30 cases, with a fresh holdout.
6. Vessel model and band calibration (about 2 days).

**Pass bar:** beat the null MAE and get `trend_ok` on at least 60 % of held-out series, with band
coverage near nominal.

## B6. Robot plan
The first robot round runs on a self-building lab in a 96-well plate:
- About 60 % of the wells are inside the validated region and 40 % are extrapolations, each
  labelled.
- Replicates and the nearest known recipe serve as controls.
- Measurements: UV-Vis and DLS, plus TEM on a subset to anchor the size readout.
- The vessel link (8) is recalibrated on the plate's heat-up curve before the run.
