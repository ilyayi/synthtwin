```json
{
 "id": "onboard-data",
 "name": "Onboard a data source",
 "version": "1.0",
 "phases": [],
 "purpose": "Bring a new data source (paper corpus, recipe dataset, benchmark set, our own robot results) into the index with provenance, so search, calibration and benchmarks can use it.",
 "inputs": [
  {
   "name": "source",
   "what": "the dump, corpus or log: where it came from, its licence, its format"
  }
 ],
 "outputs": [
  {
   "name": "index rows",
   "what": "one row per synthesis in the shared index schema",
   "schema": "see ## index_row"
  },
  {
   "name": "registry entry",
   "what": "source, licence, date, counts, who ran the onboarding"
  }
 ],
 "steps": [
  {
   "id": "provenance",
   "name": "Record provenance and licence",
   "does": "where the data came from, under what licence, and what we may use it for",
   "gate": "licence recorded before any row is kept"
  },
  {
   "id": "map",
   "name": "Map to the index rows",
   "does": "each record becomes one row in the schema of ## index_row",
   "gate": "no unmapped required field"
  },
  {
   "id": "dedupe",
   "name": "Dedupe",
   "does": "one row per synthesis, keyed by DOI + material + title",
   "gate": "no duplicate DOIs remain"
  },
  {
   "id": "normalise",
   "name": "Normalise units",
   "does": "conditions and outcomes into the canonical keys with their units; numbers only",
   "gate": "every value numeric with a unit"
  },
  {
   "id": "blind",
   "name": "Seal benchmark answers",
   "does": "if the source is a benchmark set, outcomes go to the vault and are never used for calibration or search",
   "gate": "vault holds them; only anchors visible"
  },
  {
   "id": "smoke",
   "name": "Smoke check",
   "does": "counts per material and method, sample rows read back, one row checked against its paper",
   "gate": "counts plausible, samples clean"
  },
  {
   "id": "register",
   "name": "Register the source",
   "does": "an entry names the source, its licence and the run, so every later record can carry it",
   "gate": "registry entry exists"
  }
 ],
 "rules": [
  "every record carries its source",
  "an outcome is mined only from the same sentence as its value, with its unit",
  "benchmark answers are never used for calibration, search or fitting",
  "a family with fewer than 3 recipes is thin; thin coverage is reported as thin"
 ],
 "tools": [
  "index",
  "vault",
  "library"
 ],
 "prompts": {}
}
```

Run outside a study, whenever a new corpus, dataset or result log arrives. The row schema is
the one the auto-screener's index uses (`synthtwin/screen/index.py` on the screener branch), so
onboarded sources are searchable by the screener and by the prior phase alike.

## index_row
One compact row per synthesis (snake_case, plain JSON):

    id        content hash of doi|material|title (12 hex chars)
    material  what was made            category  its class (e.g. "colloidal nanoparticle")
    method    how it was made          title     paper title
    abstract  paper abstract           doi, url  where it was published
    year      publication year         n_steps   synthesis steps
    n_cond    steps with temperature or duration conditions
    reagents  starting materials (first 12)
    src       the onboarded source's registry name

Structured steps stay in the source dump; only their counts travel in the row. Robot results
onboard through the same schema with src="robot" and their measured outcomes.
