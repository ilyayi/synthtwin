```json
{
 "id": "visualize",
 "name": "Visualise the study",
 "version": "1.0",
 "phases": [],
 "purpose": "One honest visual per scale for every study, rendered from simulation output or the exact model input, never from decoration.",
 "inputs": [
  {
   "name": "method output",
   "what": "what a simulation produced: trajectories, structures, fields, populations, spectra, plates, curves"
  }
 ],
 "outputs": [
  {
   "name": "viz.json",
   "what": "the visual manifest a method writes next to its outputs",
   "schema": "see ## viz_json"
  }
 ],
 "steps": [
  {
   "id": "kind",
   "name": "Pick the kind",
   "does": "the render kind follows the output (see ## render_kinds)",
   "gate": "kind matches the data, not the audience"
  },
  {
   "id": "scale",
   "name": "One per scale",
   "does": "reactor, molecular, atomistic: each scale of the stack gets its visual",
   "gate": "every scale represented"
  },
  {
   "id": "render",
   "name": "Render from the data",
   "does": "every frame from simulation output or the exact model input; overlays printed from the data of that frame",
   "gate": "no decorative element that poses as a result"
  },
  {
   "id": "caption",
   "name": "Caption with provenance",
   "does": "one line: what produced it, at which conditions, and anything exaggerated (e.g. 'radii drawn x8')",
   "gate": "kind_of labelled result or model-input"
  },
  {
   "id": "manifest",
   "name": "Write viz.json",
   "does": "the ## viz_json contract next to the outputs, so the UI can show them",
   "gate": "paths relative and present"
  }
 ],
 "rules": [
  "every frame comes from simulation output or the exact model input a simulation uses",
  "a structure not yet simulated is labelled 'model input', never 'result'",
  "overlay numbers (time, size, count) are printed from the data, never typed",
  "captions state provenance and every exaggeration",
  "GPU renders go through the shared render queue; one render at a time, temperature-gated; keep outputs within the size limits (stills 1920x1080, clips <= 25 MB, out/ under 400 MB)"
 ],
 "tools": [
  "renderer",
  "overlay",
  "charts"
 ],
 "prompts": {}
}
```

Runs after a method produces output, outside any phase. Reference implementations are
being built in a separate render workspace; this protocol is the contract they follow.

## render_kinds
- trajectory -> atoms: spheres on real coordinates (colour by a computed property)
- structure -> ball-and-stick (elements by convention, ligands as licorice)
- field -> cut-plane colour map (perceptual colormap, units in the legend)
- population -> particle ensemble: positions seeded, radii from the frame's distribution
- spectrum -> perceived colour: spectrum -> CIE XYZ -> sRGB under D65, plus the curve
- plate -> per-well values coloured by the quantity of that well
- vessel/process -> flask or plate with the process state (temperature, mixing, volume)
- curve -> chart
## viz_json
A JSON list written next to the method's outputs; each entry:

    {"kind": "trajectory|structure|field|population|spectrum|plate|vessel|curve",
     "scale": "reactor|molecular|atomistic",
     "link": "the chain link id it serves",
     "data": "relative path to the file(s) that drive the render",
     "title": "at most 8 words",
     "caption": "one sentence: provenance + exaggerations",
     "kind_of": "result|model-input",
     "source": "the script and data file that made it"}
