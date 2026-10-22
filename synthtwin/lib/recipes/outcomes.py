"""Outcome mining from free text: sizes, size spread, LSPR peak, DLS.

Called by synthtwin.lib.recipes.ingest with the paper abstract, the structured
notes and the step texts (in that order; the first statement per quantity
wins). Every value must come with particle context words, so a laser
wavelength or a deposited-layer thickness never becomes a size.
"""
from __future__ import annotations

import re

from synthtwin.core.schemas import Outcome

_NUM = r"(\d+(?:\.\d+)?)"
_PM = r"(?:\s*(?:±|\+/-)\s*(\d+(?:\.\d+)?))?"

_SIZE_PATTERNS = [
    # "average particle size of 15 ± 2 nm", "diameters were ~20 nm" - but not
    # "hydrodynamic diameter", which is the DLS size, a separate quantity
    re.compile(
        r"(?<!hydrodynamic )(?<!z-average )(?:average\s+|mean\s+|avg\.?\s+)?"
        r"(?:particle|nanoparticle|nanocrystal|crystallite|"
        r"nanocluster|grain|quantum[\s-]?dot|sphere|colloid|nanorod)s?\s+"
        r"(?:size|diameter)(?:s)?\s*(?:of|was|were|is|are|:|=|~|≈|about|around|"
        r"approximately)?\s*" + _NUM + _PM + r"\s*nm", re.I),
    # "Au nanoparticles of 15 ± 2 nm", "NPs measuring 10 nm", "particles
    # averaged 10 nm"
    re.compile(
        r"(?:nanoparticles?|NPs?|nanocrystals?|particles?|clusters?|spheres?|"
        r"dots?|nanorods?)\s+(?:of|with|measuring|having|averag\w*|about|around|"
        r"approximately|~|≈|:)?\s*(?:an?\s+)?(?:average\s+)?"
        r"(?:size(?:s)?|diameter(?:s)?\s+(?:of|was|=)?\s*)?" + _NUM + _PM + r"\s*nm",
        re.I),
    # "15 ± 2 nm Au nanoparticles" (size before the noun)
    re.compile(
        _NUM + _PM + r"\s*nm(?:[-\s]sized)?\s+(?:(?:gold|silver|au|ag|metal|"
        r"monodisperse|uniform|spherical|citrate)\s+){0,3}"
        r"(?:nanoparticles?|NPs?|nanocrystals?|particles?|clusters?|spheres?|dots?)",
        re.I),
    # "diameters of 5 nm" without a noun nearby (again not hydrodynamic)
    re.compile(
        r"\b(?<!hydrodynamic )(?<!z-average )(?:size|diameter)(?:s)?\s+"
        r"(?:of|was|were|=|:|~|≈)?\s*" + _NUM + _PM + r"\s*nm", re.I),
]
_SD_RE = re.compile(
    r"(?:standard\s+deviation|std\.?\s*dev\.?|\bSD\b)\s*(?:of|was|:|=)?\s*"
    r"(?:±\s*)?" + _NUM + r"\s*nm", re.I)
_CV_RE = re.compile(
    r"(?:coefficient\s+of\s+variation|\bCV\b)\s*(?:of|was|:|=)?\s*" + _NUM
    + r"\s*%", re.I)
_LSPR_RE = re.compile(
    r"(?:plasmon|\bSPR\b|\bLSPR\b|absorption|absorbance|extinction)\b[^.]{0,80}?"
    r"(?:\bat\b|\bof\b|\bnear\b|centered\s+at|~|≈|=|:)?\s*(\d{3}(?:\.\d+)?)\s*nm",
    re.I)
_DLS_RE = re.compile(
    r"(?:hydrodynamic\s+(?:diameter|size|radius)|z[\s-]?average[^.]{0,30}?)"
    r"\s*(?:of|was|=|:|~|≈)?\s*" + _NUM + r"\s*nm", re.I)
_PDI_RE = re.compile(
    r"(?:polydispersity\s+index|\bPDI\b)\s*(?:of|was|:|=|\))?\s*" + _NUM, re.I)

_METHOD_WORDS = [
    ("TEM", r"\bTEM\b|transmission\s+electron"),
    ("SEM", r"\bSEM\b|scanning\s+electron"),
    ("DLS", r"\bDLS\b|dynamic\s+light\s+scattering"),
    ("UV-Vis", r"\bUV[-\s]?vis(?:ible)?\b|\bUV\b"),
    ("SAXS", r"\bSAXS\b|small[\s-]angle\s+[xX]-?ray\s+scattering"),
    ("XRD", r"\bXRD\b|[xX]-?ray\s+diffraction"),
    ("AFM", r"\bAFM\b|atomic\s+force"),
]


def _method_near(text: str, start: int, end: int) -> str:
    """First measurement method named within +-70 chars of a match."""
    window = text[max(0, start - 70):end + 70]
    for method, pattern in _METHOD_WORDS:
        if re.search(pattern, window):
            return method
    return ""


def _first(patterns, text):
    """Earliest match over all patterns (text position first, pattern order
    as tiebreak): the first size statement in the text wins."""
    best = None
    for i, pattern in enumerate(patterns):
        m = pattern.search(text)
        if m and (best is None or (m.start(), i) < (best[0].start(), best[1])):
            best = (m, i)
    return best if best else (None, -1)


def parse_outcomes(texts: list[tuple[str, str]]) -> list[Outcome]:
    """Labelled texts -> Outcome list (size_mean_nm, size_sd_nm, size_cv_pct,
    lspr_nm, dls_z_nm, dls_pdi). Scans texts in order; the first statement
    per quantity wins; 'source' records where it was found."""
    found: dict[str, Outcome] = {}
    for label, text in texts:
        if not text:
            continue
        m, _ = _first(_SIZE_PATTERNS, text)
        if m and "size_mean_nm" not in found:
            mean = float(m.group(1))
            if 0.5 <= mean <= 1000.0:
                method = _method_near(text, m.start(), m.end())
                found["size_mean_nm"] = Outcome(
                    quantity="size_mean_nm", value=mean, unit="nm", method=method,
                    source=label)
                if m.group(2):  # "15 ± 2 nm" -> sd from the same statement
                    found["size_sd_nm"] = Outcome(
                        quantity="size_sd_nm", value=float(m.group(2)), unit="nm",
                        method=method, source=label)
        for quantity, pattern, unit, lo, hi in (
            ("size_sd_nm", _SD_RE, "nm", 0.0, 500.0),
            ("size_cv_pct", _CV_RE, "%", 0.0, 100.0),
            ("lspr_nm", _LSPR_RE, "nm", 300.0, 1000.0),
            ("dls_z_nm", _DLS_RE, "nm", 1.0, 1000.0),
            ("dls_pdi", _PDI_RE, "", 0.0, 3.0),
        ):
            if quantity in found:
                continue
            m = pattern.search(text)
            if not m:
                continue
            value = float(m.group(1))
            if not lo <= value <= hi:
                continue
            method = "DLS" if quantity.startswith("dls") else _method_near(text, m.start(), m.end())
            found[quantity] = Outcome(
                quantity=quantity, value=value, unit=unit, method=method, source=label)
    return list(found.values())
