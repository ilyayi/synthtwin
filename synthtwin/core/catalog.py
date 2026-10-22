"""Simulation methods the study agent can put in a stack.

Each method says what it gives, which scale it covers, how long it takes,
whether this install can run it now, and when it helps. Status:
    runnable     runs inside the study (seconds to minutes)
    cached       results from an earlier study are shipped (Au/Ag only)
    literature   published values, looked up rather than computed
    queued       can run on the GPU/CPU pool but takes hours or days; the
                 study records a job request instead of waiting
    planned      not built yet; listed so the gap is visible
"""
from __future__ import annotations

NP_MATERIALS = ("Au", "Ag")

METHODS: list[dict] = [
    {
        "id": "continuum", "name": "Continuum population-balance model", "scale": "reactor (mL, minutes)",
        "gives": "size mean/SD/CV, LSPR, DLS z-average/PDI with uncertainty bands for any recipe",
        "insight": "maps how each knob moves size and spread; finds recipes that hit the target",
        "est": "0.3 s per recipe; ~1 min for a full map", "seconds": 60, "status": "runnable",
        "materials": NP_MATERIALS, "default": True,
        "helps_when": "always for Au/Ag colloids: it is the only method that predicts the measured outcome",
    },
    {
        "id": "calibration", "name": "Calibration on related studies", "scale": "reactor",
        "gives": "1-2 fitted rate scales per family from one anchor point of a related study",
        "insight": "absorbs unreported details (mixing, impurities) that shift absolute size",
        "est": "~10 s per study", "seconds": 30, "status": "runnable",
        "materials": NP_MATERIALS, "default": True,
        "helps_when": "a related study measured the same quantity; the benchmark shows whether it helps",
    },
    {
        "id": "mie", "name": "Mie optics", "scale": "particle",
        "gives": "UV-Vis extinction spectrum, LSPR peak and width from the size distribution",
        "insight": "what the robot's UV-Vis should show, so a run can be checked in seconds",
        "est": "included in each prediction", "seconds": 0, "status": "runnable",
        "materials": NP_MATERIALS, "default": True,
        "helps_when": "the target or the robot's check is optical (LSPR, colour)",
    },
    {
        "id": "dls", "name": "DLS model", "scale": "particle",
        "gives": "hydrodynamic z-average and PDI including the ligand shell",
        "insight": "links the robot's DLS reading to the core size",
        "est": "included in each prediction", "seconds": 0, "status": "runnable",
        "materials": NP_MATERIALS, "default": True,
        "helps_when": "the robot measures DLS",
    },
    {
        "id": "dft_lit", "name": "Literature DFT", "scale": "atoms (surfaces, adsorbates)",
        "gives": "facet surface energies, ligand adsorption energies",
        "insight": "physical surface energy and capping strength instead of fitted defaults",
        "est": "minutes (lookup)", "seconds": 5, "status": "literature",
        "materials": "any", "default": True,
        "helps_when": "surface energy or capping binding is a sensitive model parameter",
    },
    {
        "id": "md_eam", "name": "Classical MD (EAM)", "scale": "1-10 nm clusters, ns",
        "gives": "size-dependent surface energy, melting, coalescence of particle pairs vs size and T",
        "insight": "whether small particles merge (spread, early growth) and how ripening depends on size",
        "est": "cached for Au/Ag (12.5 GPU-h done); ~12 GPU-h on 3 GPUs for a new metal", "seconds": 5,
        "status": "cached", "materials": NP_MATERIALS, "default": False,
        "helps_when": "the outcome depends on coalescence or ripening (spread targets, high T, low capping)",
    },
    {
        "id": "dft_new", "name": "New DFT (plane-wave, GPU)", "scale": "atoms, static",
        "gives": "adsorption energies of a new ligand/solvent pair, facet energies of a new material",
        "insight": "capping strength for chemistry no paper has computed",
        "est": "hours to days per system (GPU pool)", "seconds": 86400, "status": "queued",
        "materials": "any", "default": False,
        "helps_when": "the capping agent or material has no published DFT and its binding is sensitive",
    },
    {
        "id": "reaxff", "name": "Reactive MD (ReaxFF)", "scale": "10k atoms, 1 ns",
        "gives": "reduction and early cluster formation in explicit solvent",
        "insight": "mechanism of nucleation; rates are qualitative (potential not validated for this chemistry)",
        "est": "~17 h per 1 ns run on one GPU", "seconds": 61200, "status": "queued",
        "materials": "any", "default": False,
        "helps_when": "the question is about mechanism rather than the final size",
    },
    {
        "id": "kmc", "name": "Kinetic Monte Carlo", "scale": "particle ensemble, s-min",
        "gives": "facet-resolved growth, shape selection, rare events",
        "insight": "shape (rods, plates) and facet-dependent capping effects",
        "est": "~1 day to build for a new system, then minutes per run", "seconds": 86400, "status": "planned",
        "materials": "any", "default": False,
        "helps_when": "the target is a shape or anisotropy the continuum model does not resolve",
    },
    {
        "id": "mlip", "name": "Machine-learned potential (DeePMD)", "scale": "100k atoms, ns, DFT accuracy",
        "gives": "MD at near-DFT accuracy with solvent and ligands",
        "insight": "coalescence and ligand exchange with chemistry classical potentials miss",
        "est": "days (DFT training set + training)", "seconds": 259200, "status": "queued",
        "materials": "any", "default": False,
        "helps_when": "classical MD is known to be wrong for the interface and the effect matters",
    },
    {
        "id": "aimd", "name": "Ab initio MD", "scale": "~500 atoms, ps",
        "gives": "reaction free energies in explicit water",
        "insight": "reduction mechanism at the atomistic level",
        "est": "weeks", "seconds": 1814400, "status": "queued",
        "materials": "any", "default": False,
        "helps_when": "rarely for recipe design: far over budget for the information it adds",
    },
    {
        "id": "cfd", "name": "Mixing / CFD", "scale": "reactor geometry",
        "gives": "mixing time and local supersaturation at injection",
        "insight": "why scale-up or a different stirring rate changes the size",
        "est": "hours to build per geometry", "seconds": 14400, "status": "planned",
        "materials": "any", "default": False,
        "helps_when": "the recipe changes volume, injection rate or vessel",
    },
    {
        "id": "phase_field", "name": "Phase-field growth", "scale": "single particle, um",
        "gives": "morphology evolution (dendrites, branches)",
        "insight": "branched or anisotropic shapes",
        "est": "planned", "seconds": 86400, "status": "planned",
        "materials": "any", "default": False,
        "helps_when": "shape is the target",
    },
    {
        "id": "bo", "name": "Bayesian optimisation over the model", "scale": "recipe space",
        "gives": "recipes that hit the target, ranked, with diversity",
        "insight": "the recipe to run, plus alternatives",
        "est": "~30 s", "seconds": 30, "status": "runnable",
        "materials": NP_MATERIALS, "default": True,
        "helps_when": "always, once the simulator is trusted",
    },
]
BY_ID = {m["id"]: m for m in METHODS}


def available(method: dict, material: str) -> bool:
    return method["materials"] == "any" or material in method["materials"]


def default_stack(material: str, targets: list[str], knobs: list[str]) -> list[dict]:
    """Rule-based starting stack; the agent then explains and the user narrows it."""
    out = []
    for m in METHODS:
        ok = available(m, material)
        sel = ok and m["default"]
        why = m["helps_when"]
        if m["id"] == "md_eam" and ok and any(t in ("size_sd_nm", "size_cv_pct", "dls_pdi") for t in targets):
            sel, why = True, "spread is a target and coalescence of small particles sets the spread"
        if m["id"] == "md_eam" and ok and "temperature_C" in knobs:
            sel, why = True, "temperature is a knob: MD gives the size- and T-dependent coalescence"
        if m["id"] in ("mie",) and not any(t.startswith("lspr") for t in targets):
            why = "used for the robot's UV-Vis check even when LSPR is not a target"
        if not ok:
            why = f"no {m['name'].lower()} model for {material} here yet"
        out.append({"id": m["id"], "selected": bool(sel), "why": why, "insight": m["insight"]})
    return out


def estimate(selected: list[str]) -> dict:
    """Wall time of the selected stack: what runs now vs what would be queued."""
    now = sum(BY_ID[i]["seconds"] for i in selected if BY_ID[i]["status"] in ("runnable", "cached", "literature"))
    queued = [i for i in selected if BY_ID[i]["status"] == "queued"]
    planned = [i for i in selected if BY_ID[i]["status"] == "planned"]
    return {"now_s": now, "queued": queued, "planned": planned,
            "queued_s": sum(BY_ID[i]["seconds"] for i in queued)}


def generic_estimate(methods: list[dict]) -> dict:
    """Wall time of a designed (non-catalog) stack: what it says it runs now."""
    sel = [m for m in methods if m.get("selected")]
    return {"now_s": int(60 * sum(float(m.get("est_min") or 0) for m in sel)), "queued": [], "planned": [],
            "queued_s": 0, "generic": True}
