"""Optics of Au/Ag nanospheres: Bohren-Huffman Mie theory, ensemble spectra.

The metal permittivity is the Johnson & Christy (1972) table shipped in
synthtwin/np/data/johnson_christy_1972.csv (n, k vs photon energy, Phys. Rev. B
6, 4370), interpolated in energy, with the free-electron damping corrected for
the particle radius r (surface scattering, Kreibig & Vollmer 1995):

    eps(w, r) = eps_JC(w) + wp^2 / (w^2 + i w g_bulk) - wp^2 / (w^2 + i w g(r)),
    g(r) = g_bulk + A hbar vF / r.

Each particle is a metal core inside its ligand/adsorbate shell (thickness
ligand_shell_nm, refractive index shell_n + surface_layer_dn) in water (n_medium). The Mie
coefficients are those of a coated sphere (Bohren & Huffman 1983, BHCOAT;
with no shell it is the plain BHMIE sphere): logarithmic derivatives D_n by
downward recurrence, Riccati-Bessel psi, chi by upward recurrence.
Everything is vectorized over (sizes, wavelengths).

`cext_table(material, p)` caches C_ext (m2) on growth.D_CENTERS_NM x WAVELENGTHS_NM;
`ensemble_spectrum(hist, ...)` is absorbance for a 1 cm path from a number
histogram (per m3); `peak(...)` returns lspr_nm and lspr_fwhm_nm.
`s1_intensity(material, p, d_nm, wavelength_nm, angle_deg)` gives |S1|^2 for DLS.
Called by model.py and dls.py.
"""
from __future__ import annotations

import csv
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

HBAR_EV_S = 6.582119569e-16
HC_EV_NM = 1239.84198
DATA = Path(__file__).parent / "data" / "johnson_christy_1972.csv"
WAVELENGTHS_NM = np.arange(300.0, 1000.0 + 1e-9, 2.0)
PEAK_WINDOW_NM = {"Au": (470.0, 800.0), "Ag": (360.0, 700.0)}


@lru_cache(maxsize=1)
def _jc_table() -> dict[str, np.ndarray]:
    with open(DATA, newline="") as fh:
        rows = [r for r in csv.reader(line for line in fh if not line.startswith("#"))]
    head, body = rows[0], np.array(rows[1:], dtype=float)
    return {h: body[:, i] for i, h in enumerate(head)}


def eps_bulk(material: str, wavelength_nm: np.ndarray) -> np.ndarray:
    """Complex permittivity (n + ik)^2 from Johnson & Christy, linear in energy."""
    t = _jc_table()
    e = HC_EV_NM / np.asarray(wavelength_nm, dtype=float)
    n = np.interp(e, t["energy_eV"], t[f"{material}_n"])
    k = np.interp(e, t["energy_eV"], t[f"{material}_k"])
    return (n + 1j * k) ** 2


def eps_particle(material: str, wavelength_nm: np.ndarray, r_nm: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    """(sizes, wavelengths) permittivity with the size-dependent Drude damping."""
    w = (HC_EV_NM / np.asarray(wavelength_nm, dtype=float))[None, :]          # eV
    wp, gb = float(p["wp_eV"]), float(p["gamma_bulk_eV"])
    g_r = gb + float(p["A_damping"]) * HBAR_EV_S * float(p["vF_m_s"]) / (np.asarray(r_nm, dtype=float)[:, None] * 1e-9)
    return (eps_bulk(material, wavelength_nm)[None, :]
            + wp ** 2 / (w ** 2 + 1j * w * gb) - wp ** 2 / (w ** 2 + 1j * w * g_r))


def _dn_down(z: np.ndarray, nmax: int) -> np.ndarray:
    """Logarithmic derivative D_n(z), n = 0..nmax+, by downward recurrence."""
    nmx = int(max(nmax, np.abs(z).max()) + 16)
    D = np.zeros((nmx + 1,) + z.shape, dtype=complex)
    for n in range(nmx, 0, -1):
        D[n - 1] = n / z - 1.0 / (D[n] + n / z)
    return D


def coated_ab(m1: np.ndarray, m2: float, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mie a_n, b_n (n = 1..N) of a coated sphere (Bohren & Huffman BHCOAT):
    core index m1 and coat index m2 relative to the medium, size parameters x
    (core) and y (outer), shaped (S, W). The D_n are taken by downward
    recurrence (stable for the absorbing metal core). With y = x it is the
    plain Mie sphere. Returns arrays (N, S, W)."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    N = int(np.ceil(y.max() + 4.0 * y.max() ** (1.0 / 3.0) + 2.0))
    x1, x2, y2 = m1 * x, m2 * x + 0j, m2 * y + 0j
    D1, D2, Dy = _dn_down(x1, N), _dn_down(x2, N), _dn_down(y2, N)
    psi0, psi1, chi0, chi1 = np.cos(y), np.sin(y), -np.sin(y), np.cos(y)
    xi1 = psi1 - 1j * chi1
    c0x, c1x, c0y, c1y = -np.sin(x2), np.cos(x2), -np.sin(y2), np.cos(y2)
    a = np.zeros((N,) + y.shape, dtype=complex)
    b = np.zeros_like(a)
    for n in range(1, N + 1):
        psi = (2 * n - 1) / y * psi1 - psi0
        chi = (2 * n - 1) / y * chi1 - chi0
        xi = psi - 1j * chi
        chix = (2 * n - 1) * c1x / x2 - c0x
        chiy = (2 * n - 1) * c1y / y2 - c0y
        chipx, chipy = c1x - n * chix / x2, c1y - n * chiy / y2
        common = chix * D2[n] - chipx
        an = (m2 * D1[n] - m1 * D2[n]) / (m2 * D1[n] * chix - m1 * chipx) / common
        bn = (m2 * D2[n] - m1 * D1[n]) / (m2 * chipx - m1 * D1[n] * chix) / common
        brack, crack = an * (chiy * Dy[n] - chipy), bn * (chiy * Dy[n] - chipy)
        dn = (Dy[n] - brack * chipy) / (1.0 - brack * chiy)
        gn = (Dy[n] - crack * chipy) / (1.0 - crack * chiy)
        ta, tb = dn / m2 + n / y, m2 * gn + n / y
        a[n - 1] = (ta * psi - psi1) / (ta * xi - xi1)
        b[n - 1] = (tb * psi - psi1) / (tb * xi - xi1)
        psi0, psi1, chi0, chi1, xi1 = psi1, psi, chi1, chi, xi
        c0x, c1x, c0y, c1y = c1x, chix, c1y, chiy
    return a, b


def _ab(material: str, p: dict[str, Any], d_nm: np.ndarray, wl: np.ndarray):
    """(a, b, k) for metal cores of diameter d_nm with the ligand shell of p."""
    nmed = float(p.get("n_medium", 1.333))
    r = 0.5 * d_nm
    t = float(p.get("ligand_shell_nm", 0.0)) if p.get("optical_shell", True) else 0.0
    m1 = np.sqrt(eps_particle(material, wl, r, p)) / nmed
    m2 = (float(p.get("shell_n", nmed)) + float(p.get("surface_layer_dn", 0.0))) / nmed
    k = 2.0 * math.pi * nmed / (wl * 1e-9)                                     # 1/m
    x = k[None, :] * r[:, None] * 1e-9
    y = k[None, :] * (r[:, None] + t) * 1e-9
    a, b = coated_ab(m1, m2, x, y)
    return a, b, k


def cext(material: str, d_nm: np.ndarray, wavelength_nm: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    """Extinction cross-section (m2), shape (sizes, wavelengths)."""
    d_nm = np.atleast_1d(np.asarray(d_nm, dtype=float))
    a, b, k = _ab(material, p, d_nm, np.asarray(wavelength_nm, dtype=float))
    n = np.arange(1, a.shape[0] + 1)[:, None, None]
    s = ((2 * n + 1) * (a + b).real).sum(axis=0)
    return 2.0 * math.pi / k[None, :] ** 2 * s


def s1_intensity(material: str, p: dict[str, Any], d_nm: np.ndarray,
                 wavelength_nm: float = 633.0, angle_deg: float = 173.0) -> np.ndarray:
    """|S1|^2 (perpendicular polarization) at one wavelength and angle."""
    d_nm = np.atleast_1d(np.asarray(d_nm, dtype=float))
    a, b, _k = _ab(material, p, d_nm, np.array([float(wavelength_nm)]))
    mu = math.cos(math.radians(angle_deg))
    N = a.shape[0]
    pi_n = np.zeros(N + 1)
    tau_n = np.zeros(N + 1)
    pi_n[1] = 1.0
    for n in range(1, N + 1):
        if n >= 2:
            pi_n[n] = ((2 * n - 1) * mu * pi_n[n - 1] - n * pi_n[n - 2]) / (n - 1)
        tau_n[n] = n * mu * pi_n[n] - (n + 1) * pi_n[n - 1]
    n = np.arange(1, N + 1)
    c = ((2 * n + 1) / (n * (n + 1)))[:, None, None]
    s1 = (c * (a * pi_n[1:, None, None] + b * tau_n[1:, None, None])).sum(axis=0)
    return (np.abs(s1) ** 2)[:, 0]


_TABLES: dict[tuple, np.ndarray] = {}


def cext_table(material: str, p: dict[str, Any]) -> np.ndarray:
    """C_ext on growth.D_CENTERS_NM x WAVELENGTHS_NM (cached per optical params)."""
    from synthtwin.lib.np.growth import D_CENTERS_NM
    key = (material, float(p["wp_eV"]), float(p["gamma_bulk_eV"]), float(p["A_damping"]),
           float(p["vF_m_s"]), float(p.get("n_medium", 1.333)), float(p.get("ligand_shell_nm", 0.0)),
           float(p.get("shell_n", 1.333)), float(p.get("surface_layer_dn", 0.0)), bool(p.get("optical_shell", True)))
    if key not in _TABLES:
        if len(_TABLES) > 16:
            _TABLES.clear()
        _TABLES[key] = cext(material, D_CENTERS_NM, WAVELENGTHS_NM, p)
    return _TABLES[key]


def ensemble_spectrum(hist: np.ndarray, material: str, p: dict[str, Any], path_cm: float = 1.0) -> np.ndarray:
    """Number histogram (D, bins) per m3 -> absorbance (D, wavelengths), path 1 cm."""
    return np.atleast_2d(hist) @ cext_table(material, p) * (path_cm * 1e-2) / math.log(10.0)


def peak(spec: np.ndarray, material: str, wl: np.ndarray = WAVELENGTHS_NM) -> tuple[np.ndarray, np.ndarray]:
    """LSPR maximum (parabolic refinement) and FWHM for each row of `spec`.
    The FWHM is the full width at half maximum; when the blue side never falls
    to half maximum (Au interband absorption) it is twice the red half width."""
    spec = np.atleast_2d(spec)
    lo, hi = PEAK_WINDOW_NM[material]
    win = np.where((wl >= lo) & (wl <= hi))[0]
    lspr, fwhm = np.zeros(len(spec)), np.zeros(len(spec))
    for j, s in enumerate(spec):
        i = win[np.argmax(s[win])]
        if 0 < i < len(wl) - 1:
            y0, y1, y2 = s[i - 1], s[i], s[i + 1]
            den = y0 - 2 * y1 + y2
            off = 0.5 * (y0 - y2) / den if den < 0 else 0.0
        else:
            off = 0.0
        step = wl[1] - wl[0]
        lspr[j] = wl[i] + off * step
        half = 0.5 * s[i]
        red = _cross(wl[i:], s[i:], half)
        blue = _cross(wl[i::-1], s[i::-1], half)
        if red is None:
            fwhm[j] = np.nan
        elif blue is None:
            fwhm[j] = 2.0 * (red - lspr[j])
        else:
            fwhm[j] = red - blue
    return lspr, fwhm


def _cross(x: np.ndarray, y: np.ndarray, level: float) -> float | None:
    below = np.where(y < level)[0]
    if not len(below):
        return None
    k = below[0]
    return float(x[k - 1] + (level - y[k - 1]) * (x[k] - x[k - 1]) / (y[k] - y[k - 1]))
