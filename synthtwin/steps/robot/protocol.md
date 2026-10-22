```json
{
 "id": "handoff",
 "name": "Hand off to the lab",
 "version": "1.0",
 "phases": [
  "robot"
 ],
 "purpose": "Send the approved recipe to a self-building lab as a protocol package, take the measurements and run logs back, and feed them into the library and new benchmark cases.",
 "inputs": [
  {
   "name": "recipe",
   "what": "the approved proposal and its write-up"
  }
 ],
 "outputs": [
  {
   "name": "protocol package",
   "what": "steps, stocks, plate or vessel format, measurements, expected values with bands, acceptance checks"
  },
  {
   "name": "feedback",
   "what": "measured outcomes as library recipes; robot sweeps as new benchmark cases"
  }
 ],
 "steps": [
  {
   "id": "package",
   "name": "Assemble the package",
   "does": "steps, stocks, format, measurements, expected bands, acceptance checks",
   "gate": "a person approved the recipe first"
  },
  {
   "id": "capabilities",
   "name": "Check capabilities",
   "does": "the lab checks the steps against its capabilities and builds any it lacks (digital twin first)",
   "gate": "steps needing a new capability are named in the recipe"
  },
  {
   "id": "run",
   "name": "Run",
   "does": "the lab runs the protocol once approved",
   "gate": "its acceptance checks pass there"
  },
  {
   "id": "return",
   "name": "Take the results back",
   "does": "measurements and run logs; compare with the predicted band",
   "gate": "inside/outside the band recorded"
  },
  {
   "id": "feedback",
   "name": "Feed back",
   "does": "results become library recipes; sweeps become held-out benchmark cases; a failed prediction points at the link to fix",
   "gate": "the next study calibrates on them"
  }
 ],
 "rules": [
  "a person approves every experiment",
  "the robot's current capability list never filters a recipe; it only flags steps that need a new capability",
  "every returned number carries the run it came from"
 ],
 "tools": [
  "robot",
  "library"
 ],
 "prompts": {
  "robot": "robot"
 }
}
```

A8/A9. The hand-off text sent with each request is written by the engine
(_confirm_recipe); this protocol governs the package and the feedback loop.

## robot
PHASE: robot. The recipe was offered to the robotic platform. Answer questions about running it and about entering the measured results (they become a new library recipe for the next study).
