"""Physics overrides for the nanoparticle simulator (``synthtwin.lib.np``).

    from synthtwin.lib.atomistic.params import physics_overrides
    params["physics"] = physics_overrides("Au", "citrate", strip=True)

``physics_overrides(material, capping)`` returns the six simulator physics
names (gamma_J_m2, Vm_m3_mol, coalescence_dmax_nm, coalescence_eff,
capping_dG_eV, ligand_shell_nm) plus ``_uncertainty`` (1 sigma, same keys),
``_sources`` (same keys -> list of strings) and ``_grade`` (same keys ->
"strong" | "moderate" | "weak"). ``strip=True`` drops the underscore keys.
With capping=None the capping-dependent entries (capping_dG_eV,
ligand_shell_nm) are omitted and gamma is the bare (uncapped) value.

Values come from ``data/derived_params.json`` (written by ``derive.py`` from
the literature table and the MD summaries); see docs/reports/atomistic.md.

Note on gamma: these are physical metal/water interfacial energies
(~1.1-1.3 J/m2). The simulator defaults (0.25-0.30) are effective values; a
physical gamma makes the CNT barrier ~60x larger and Gibbs-Thomson ~4x
stronger, so the nucleation prefactor/calibration has to be re-fitted when it
is used (see the report).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
NAMES = ("gamma_J_m2", "Vm_m3_mol", "coalescence_dmax_nm", "coalescence_eff", "capping_dG_eV", "ligand_shell_nm")
CAPPINGS = ("none", "citrate", "tannic", "pvp", "ctab")
MATERIALS = ("Au", "Ag")
_ALIASES = {"tannic_acid": "tannic", "ta": "tannic", "polyvinylpyrrolidone": "pvp", "cetrimonium": "ctab",
            "sodium_citrate": "citrate", "trisodium_citrate": "citrate", None: None}


@lru_cache(maxsize=1)
def derived() -> dict:
    return json.loads((DATA / "derived_params.json").read_text())


def _canon_capping(capping):
    if capping is None:
        return None
    c = str(capping).strip().lower().replace(" ", "_").replace("-", "_")
    c = _ALIASES.get(c, c)
    if c not in CAPPINGS:
        raise ValueError(f"unknown capping {capping!r}; expected one of {CAPPINGS}")
    return c


def physics_overrides(material: str, capping: str | None = None, strip: bool = False) -> dict:
    m = str(material).strip().capitalize()
    if m not in MATERIALS:
        raise ValueError(f"unknown material {material!r}; expected one of {MATERIALS}")
    c = _canon_capping(capping)
    D = derived()
    mat = D["materials"][m]
    rec = D["recommended"][m]
    from . import literature as L

    vals, unc, src, grade = {}, {}, {}, {}
    g = mat["gamma"][c or "none"]
    vals["gamma_J_m2"], unc["gamma_J_m2"], src["gamma_J_m2"] = g["value"], g["unc"], g["sources"]
    grade["gamma_J_m2"] = "moderate"
    vals["Vm_m3_mol"], unc["Vm_m3_mol"] = mat["Vm_m3_mol"]["value"], mat["Vm_m3_mol"]["unc"]
    src["Vm_m3_mol"], grade["Vm_m3_mol"] = [L.cite(f"crc_{m}_Vm")], "strong"
    for k in ("coalescence_dmax_nm", "coalescence_eff"):
        vals[k], unc[k], src[k], grade[k] = rec[k]["value"], rec[k]["unc"], rec[k]["sources"], rec[k]["grade"]
    if c is not None:
        cap = D["capping"][c]
        vals["capping_dG_eV"], unc["capping_dG_eV"] = cap["dG"][m]
        src["capping_dG_eV"] = [cap["src_dG"]] + [L.cite(i) for i in cap.get("lit_dG", [])]
        grade["capping_dG_eV"] = cap.get("grade_dG", "weak")
        vals["ligand_shell_nm"], unc["ligand_shell_nm"] = cap["shell"][m]
        src["ligand_shell_nm"] = [cap["src_shell"]] + [L.cite(i) for i in cap.get("lit_shell", [])]
        grade["ligand_shell_nm"] = cap.get("grade_shell", "weak")
    vals = {k: float(v) for k, v in vals.items()}
    if strip:
        return vals
    return {**vals, "_uncertainty": unc, "_sources": src, "_grade": grade}


def table() -> list[dict]:
    """All (material, capping) combinations, for the report."""
    rows = []
    for m in MATERIALS:
        for c in CAPPINGS:
            p = physics_overrides(m, c)
            rows.append({"material": m, "capping": c,
                         **{k: (p[k], p["_uncertainty"][k]) for k in NAMES}})
    return rows
