"""Dynamic light scattering readout (cumulant z-average and PDI) of a size histogram.

A Zetasizer-type instrument (633 nm laser, backscatter at 173 deg, vertical
polarization) weights each particle by its scattered intensity |S1|^2 from Mie
theory (optics.s1_intensity; metal core in its ligand shell in water) and
measures the hydrodynamic diameter d_h = d_core + 2 * ligand_shell_nm. The
cumulant fit gives (ISO 22412)

    z-average = sum(I) / sum(I / d_h)          (harmonic intensity mean),
    PDI       = var_I(1/d_h) / mean_I(1/d_h)^2 (second cumulant / first^2).

Called by model.predict. Inputs are the number histograms of growth.simulate.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from synthtwin.lib.np import optics

WAVELENGTH_NM = 633.0
ANGLE_DEG = 173.0
_CACHE: dict[tuple, np.ndarray] = {}


def intensity_table(material: str, p: dict[str, Any]) -> np.ndarray:
    """|S1|^2 on growth.D_CENTERS_NM (cached per optical parameters)."""
    from synthtwin.lib.np.growth import D_CENTERS_NM
    key = (material, float(p["wp_eV"]), float(p["gamma_bulk_eV"]), float(p["A_damping"]),
           float(p.get("n_medium", 1.333)), float(p.get("ligand_shell_nm", 0.0)),
           float(p.get("shell_n", 1.333)), float(p.get("surface_layer_dn", 0.0)))
    if key not in _CACHE:
        if len(_CACHE) > 16:
            _CACHE.clear()
        _CACHE[key] = optics.s1_intensity(material, p, D_CENTERS_NM, WAVELENGTH_NM, ANGLE_DEG)
    return _CACHE[key]


def z_average(hist: np.ndarray, material: str, p: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """Number histograms (D, bins) -> (z-average nm, PDI), each shape (D,)."""
    from synthtwin.lib.np.growth import D_CENTERS_NM
    hist = np.atleast_2d(hist)
    I = hist * intensity_table(material, p)[None, :]
    inv = 1.0 / (D_CENTERS_NM + 2.0 * float(p.get("ligand_shell_nm", 0.0)))
    tot = np.maximum(I.sum(axis=1), 1e-300)
    m1 = (I * inv).sum(axis=1) / tot
    m2 = (I * inv ** 2).sum(axis=1) / tot
    z = 1.0 / np.maximum(m1, 1e-300)
    pdi = np.maximum(m2 - m1 ** 2, 0.0) / np.maximum(m1 ** 2, 1e-300)
    return z, pdi
