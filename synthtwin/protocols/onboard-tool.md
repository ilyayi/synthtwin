```json
{
 "id": "onboard-tool",
 "name": "Onboard a tool",
 "version": "1.0",
 "phases": [],
 "purpose": "Add a simulation engine or method to the platform: installed into the tool area, gated by a known answer, and listed so stack designers can pick it.",
 "inputs": [
  {
   "name": "tool",
   "what": "the code: name, version, what it computes, how it is called"
  }
 ],
 "outputs": [
  {
   "name": "tool registry entry",
   "what": "name, use, run, check, version, study",
   "schema": "toolbox registry.json"
  },
  {
   "name": "catalogue entry",
   "what": "scale, gives, est, status, helps_when"
  }
 ],
 "steps": [
  {
   "id": "install",
   "name": "Install into the tool area",
   "does": "conda/pip/source builds inside the tool area only, per ## policy",
   "gate": "install check exits 0"
  },
  {
   "id": "smoke",
   "name": "Smoke test",
   "does": "it runs, prints its version, and the run command works",
   "gate": "one clean run from the registry command"
  },
  {
   "id": "known_answer",
   "name": "Known-answer gate",
   "does": "it reproduces a published value for a reference system (density, diffusivity, lattice constant, LSPR peak, ...)",
   "gate": "the check command that proves it exits 0"
  },
  {
   "id": "register",
   "name": "Register it",
   "does": "python register.py --name ... --check ... so later studies reuse it",
   "gate": "registry.json entry with the passing check"
  },
  {
   "id": "catalogue",
   "name": "Catalogue entry",
   "does": "scale, gives, est, status, so the stack designer sees it",
   "gate": "listed with an honest est"
  },
  {
   "id": "report",
   "name": "Declare its outputs",
   "does": "what it returns, with units and uncertainty, including its visual (see the visualize protocol)",
   "gate": "outputs and visual kind named"
  }
 ],
 "rules": [
  "installs only inside the tool area, only from official sources",
  "a tool is used only after its known-answer check passes",
  "every registered tool is listed to every later builder: install once, reuse"
 ],
 "tools": [
  "toolbox",
  "catalogue"
 ],
 "prompts": {
  "toolbox.policy": "policy"
 }
}
```

Run outside a study. The `## policy` section is the tool-area install policy the builders
receive verbatim; {prefix}, {conda} and {study} are substituted per build. A benchmark set of
known answers per method is kept so the gate is not re-argued each time.

## policy
- You MAY install any software a method would benefit from (codes, force fields, Python packages,
  pseudopotential/potential libraries), but only inside the tool area {prefix}:
  - check `{prefix}/registry.json` first and reuse what is there;
  - conda: `flock {prefix}/.lock {conda} create -y -p {prefix}/envs/<name> --override-channels -c conda-forge <pkgs>`
    (or `install -p {prefix}/envs/<name>` to extend one); put stacks that conflict in separate envs;
  - pip: `{prefix}/envs/<env>/bin/pip install <pkg>`;
  - source builds: clone or unpack into {prefix}/src/<name>, install into {prefix}/opt/<name>
    (e.g. `cmake -DCMAKE_INSTALL_PREFIX={prefix}/opt/<name>`), `nice -n 10 make -j8`; GPU builds target CUDA
    arch 86 (RTX 30xx);
  - run long installs and builds through simjob.py; check `df -h ~` first and stop if under 20 GB would remain;
  - get software only from its official source (conda-forge, PyPI, the project's own repository or website);
    never sudo or system package managers; never touch the base conda env or envs outside the tool area;
    never install on other machines; skip software that needs a paid licence or registration (say so);
  - when a tool works, register it so later studies can use it:
    `python {prefix}/register.py --name N --use "..." --run "..." --check "<command that proves it works>"
    --version V --study {study}`; record the software and version per method in report.json.
