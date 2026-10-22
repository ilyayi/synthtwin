# SynthTwin

**Self-driving labs can run any recipe. Which recipe to run is still the hard part.**

SynthTwin is an AI research assistant for chemical synthesis. You tell it what you
want to make. It reads the literature, builds a physics simulation of your
experiment, checks that simulation against published results, and hands a robot
(or you) a recipe that was already tried in silico.

## Why

- Robots can now run syntheses on their own. Choosing *what* to run still takes a
  PhD student months of reading and trial and error.
- Design of experiments and Bayesian optimization don't know the physics. They
  propose recipes that are physically impossible, so a human has to watch every step.
- SynthTwin puts the physics in the loop: every proposed recipe comes from a
  simulation that has been tested first.

## How it works: 8 steps

| # | Step | What happens |
|---|---|---|
| 1 | **Goal** | You and the agent agree on a measurable target (e.g. "CdS quantum dots emitting at 560 nm"). |
| 2 | **Related studies** | The agent finds who has tried this and what they got. |
| 3 | **Simulation stack** | The agent picks or writes simulations at each scale: reactor → particle → atoms. |
| 4 | **Benchmark sample** | It picks the published studies the simulation must predict before it is trusted. |
| 5 | **Blind benchmark** | The simulation must predict published results it has never seen. |
| 6 | **Your case** | It maps your design space: what matters, where the best region is. |
| 7 | **Recipe** | It proposes conditions with checks and predicted result ranges. |
| 8 | **Robot** | It sends a protocol package to a self-driving lab. Results come back and calibrate the next study. |

You confirm each step; the agent does the work.

## What it has done so far

- **Polyimide film** (a material with no existing simulator): from the problem
  statement to a robot-ready protocol in about 16 minutes. The agent wrote and ran a
  new simulator in about 7 minutes for $1.30.
- **CdS quantum dots**: a full multi-scale simulation stack (well heating and
  evaporation, solution chemistry, nucleation and growth, surface traps, emission).
- **The rule for choosing the next experiment** was tested by replaying 5 real
  lab campaigns (Liang et al. 2021).

## What more compute unlocks

- Studies that start on their own, many at once.
- Local models on our own GPUs, with no per-token cost (switching is built in).
- Full molecular dynamics and DFT where they change the decision (the quantum-dot stack is
  about 47 compute-hours).
- Every robot result makes the next study better.

## Try it

```
pip install -e .
synthtwin-ui            # then open http://127.0.0.1:8770/#/overview
```

Start at **Overview** for the one-page picture, then open a study.

## More

- [docs/PIPELINE.md](docs/PIPELINE.md): the pipeline in detail
- [docs/BENCHMARK.md](docs/BENCHMARK.md): the blind benchmark (cards, vault, scores) and the code layout

MIT license.
