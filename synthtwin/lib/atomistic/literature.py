"""Literature values (DFT and experiment) for Au / Ag nanoparticle physics.

Data live in ``data/literature.json`` (one entry per published number, with
method, conditions, uncertainty, full citation and DOI). This module loads and
queries them; ``params.py`` combines them with the MD results.

Entry fields: id, quantity, material, facet, adsorbate, value, unit,
uncertainty, method, conditions, citation, doi, verified, note.

Definitions differ between sources (read ``conditions``/``note``): DFT
adsorption energies are vacuum binding energies at a fixed coverage, referenced
to the neutral atom/radical (Pobernik, Santiago-Rodriguez), half an X2 molecule
(Gossenberger) or the gas-phase molecule (phenol, benzene); none is a free
energy in water. Isotherm values (Dinkel) are Gibbs energies in water.
"""
from __future__ import annotations

import json
import statistics
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
QUANTITIES = {
    "surface_energy_facet", "surface_energy_avg", "surface_energy_size_trend", "adsorption_energy",
    "ligand_shell_thickness", "molar_volume", "melting_point", "tolman_length", "surface_diffusion",
    "solid_liquid_interfacial_energy", "other",
}


@lru_cache(maxsize=1)
def load() -> tuple[dict, ...]:
    """All literature entries (read once)."""
    d = json.loads((DATA / "literature.json").read_text())
    return tuple(d["entries"])


def by_id(entry_id: str) -> dict:
    for e in load():
        if e["id"] == entry_id:
            return e
    raise KeyError(entry_id)


def query(quantity: str | None = None, material: str | None = None, facet: str | None = None,
          adsorbate: str | None = None, method_contains: str | None = None) -> list[dict]:
    """Entries matching all given fields (None = any)."""
    out = []
    for e in load():
        if quantity and e["quantity"] != quantity:
            continue
        if material and e["material"] != material:
            continue
        if facet and e.get("facet") != facet:
            continue
        if adsorbate and e.get("adsorbate") != adsorbate:
            continue
        if method_contains and method_contains.lower() not in e["method"].lower():
            continue
        out.append(e)
    return out


def combine(ids: list[str]) -> tuple[float, float]:
    """Unweighted mean of the cited values and an uncertainty = max(spread
    (sample sd), mean of the quoted per-entry uncertainties)."""
    vals = [by_id(i)["value"] for i in ids]
    uncs = [by_id(i)["uncertainty"] or 0.0 for i in ids]
    mean = statistics.fmean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return mean, max(sd, statistics.fmean(uncs) if uncs else 0.0)


def cite(entry_id: str) -> str:
    e = by_id(entry_id)
    doi = f", doi:{e['doi']}" if e.get("doi") else ""
    return f"{e['citation']}{doi}"
