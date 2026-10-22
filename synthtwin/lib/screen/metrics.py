"""Figures of merit the screener can read out of titles and abstracts.

Each metric knows its application keywords (`apps`, used by `pick` when the user
names only an application) and regexes that pull the reported number out of
free text. Patterns have ONE capture group — the number, possibly a range or in
scientific notation ("18.2–20.1%", "1.2 × 10−3") — and are matched
case-insensitively on title + abstract. Unit spellings come in many flavours
(µmol g−1 h−1, mAh/g, m^2 g-1, mA h g−1, cm²/V/s) and are normalised to the
metric's base unit; values outside the metric's sane range are rejected.
"""
from __future__ import annotations

import re

# a number: plain, with thousands commas, a decimal, a range ("18.2–20.1"),
# or in scientific notation ("1.2 × 10−3"); captured as one group
_N = r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d*\.?\d+)"
N = ("(" + _N + r"(?:\s*(?:[-–—−~]|to)\s*" + _N + r")?"
     r"(?:\s*[×x]\s*10\s*(?:\^?\s*[-−–]?\s*\d+|[⁻⁺]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+))?)")
GUARD = r"(?<![\w.,;:!\-–—−])"   # the number must not continue a word or a "g-1"
PC = r"\s*(?:%|percent\b|per cent\b)"   # percent suffix
# one "per" marker: "-1", "⁻¹", "^-1", "/" or the word "per"
SEP = r"(?:\s*[−–^/-]+\s*(?:1|¹)\b|\s*\^\s*-\s*1\b|⁻¹|/|\s+per\s+)"
# between unit tokens: nothing, spaces, a middle dot, or a per marker
TS = r"(?:\s|[·])*" + SEP + r"?" + r"(?:\s|[·])*"


def _ug(*tokens: str, trailing: bool = True) -> str:
    """Unit tokens joined the way papers write them: 'mA h g-1', 'mAh/g', 'mAh·g⁻¹'."""
    body = r"".join(t + TS for t in tokens[:-1]) + tokens[-1]
    return body + (SEP + r"?" if trailing else "")


def _kw(text: str, value: str) -> str:   # "efficiency ... of X %", filler words allowed
    return (text + r"\s*(?:\(|\b(?:of|was|were|is|are|reaching|reached|approaching|about|approximately|"
            r"up to|as high as|as low as|over|above)\b)?[^.\n%\d]{0,25}?" + value)


_G = r"g(?:rams?)?\b"
# siemens per centimetre in any spelling: "S cm-1", "mS/cm", "mS cm−1"
_SCOND = (N + r"\s*" + r"(?:milli\s*)?[mµμun]?\s*[Ss](?:iemens)?\b" + TS
          + r"(?:cm|centimet(?:er|re)s?)\b" + SEP + r"?")
# µmol (or mmol) per gram per hour, either token order
_H2U = r"(?:" + r"|".join([_ug(r"(?:[µμu]|mm?)mol", _G, r"h"), _ug(r"(?:[µμu]|mm?)mol", r"h", _G)]) + r")"

METRICS: dict[str, dict] = {
    "pce": {
        "name": "power conversion efficiency", "unit": "%", "better": "max", "range": (0, 47),
        "apps": ["solar cell", "photovoltaic"],
        "patterns": [
            _kw(r"power conversion efficienc(?:y|ies)", N + PC),
            _kw(r"\bPCEs?\b", N + PC),
            _kw(r"(?:solar cell |photovoltaic |photoelectric )?(?:energy )?conversion efficienc(?:y|ies)", N + PC),
            _kw(r"(?<!quantum )(?<!QE )efficienc(?:y|ies)", N + PC),
        ]},
    "eqe": {
        "name": "external quantum efficiency", "unit": "%", "better": "max", "range": (0, 100),
        "apps": ["LED", "QLED", "light-emitting diode", "electroluminescent"],
        "patterns": [
            _kw(r"external quantum efficienc(?:y|ies)", N + PC),
            _kw(r"\bEQEs?\b", N + PC),
        ]},
    "plqy": {
        "name": "photoluminescence quantum yield", "unit": "%", "better": "max", "range": (0, 100),
        "apps": ["emitter", "LED", "phosphor", "quantum dot", "luminescent", "scintillator"],
        "patterns": [
            _kw(r"(?:photoluminescence |PL )?quantum yields?", N + PC),
            _kw(r"\bPLQYs?\b", N + PC),
        ]},
    "capacity": {
        "name": "specific capacity", "unit": "mAh g-1", "better": "max", "range": (0, 5000),
        "apps": ["battery", "anode", "cathode", "lithium-ion", "sodium-ion"],
        "patterns": [
            _kw(r"(?:reversible |specific |discharge |charge |initial )?capacity", N + r"\s*" + _ug(r"mA", r"h", _G)),
            GUARD + N + r"\s*" + _ug(r"mA", r"h", _G),
        ]},
    "bet": {
        "name": "BET surface area", "unit": "m2 g-1", "better": "max", "range": (0, 8000),
        "apps": ["porous", "adsorption", "support", "mesoporous"],
        "patterns": [
            _kw(r"(?:BET[- ])?surface areas?", N + r"\s*" + _ug(r"m\s*\^?\s*[2²]", _G)),
            _kw(r"\b(?:BET|SBET)\b", N + r"\s*" + _ug(r"m\s*\^?\s*[2²]", _G)),
        ]},
    "co2_uptake": {
        "name": "CO2 uptake", "unit": "mmol g-1", "better": "max", "range": (0, 60),
        "apps": ["CO2 capture", "carbon capture", "CO2 adsorption", "CO2 uptake", "CO2 storage"],
        "patterns": [
            _kw(r"CO[2₂]\s*(?:uptake|adsorption(?: capacity)?)", N + r"\s*" + _ug(r"mmol", _G)),
            _kw(r"\buptake\b", N + r"\s*" + _ug(r"mmol", _G)),
        ]},
    "fe": {
        "name": "Faradaic efficiency", "unit": "%", "better": "max", "range": (0, 100),
        "apps": ["CO2 reduction", "electroreduction", "CO2 electrolysis"],
        "patterns": [
            _kw(r"[Ff]aradaic efficienc(?:y|ies)", N + PC),
            _kw(r"\bFE\b", N + PC),
        ]},
    "overpotential": {
        "name": "overpotential", "unit": "mV", "better": "min", "range": (20, 2000),
        "apps": ["OER", "HER", "water splitting", "oxygen evolution", "hydrogen evolution"],
        "patterns": [
            _kw(r"overpotentials?", N + r"\s*(?:m\s*)?[Vv](?:olts?)?\b"),
            _kw(r"η\s*=?", N + r"\s*(?:m\s*)?[Vv](?:olts?)?\b"),
        ]},
    "h2_rate": {
        "name": "hydrogen evolution rate", "unit": "µmol g-1 h-1", "better": "max", "range": (0, 2e7),
        "apps": ["photocatalytic hydrogen", "hydrogen production", "hydrogen evolution", "photocatalytic H2"],
        "patterns": [
            _kw(r"(?:hydrogen|H[2₂])\s*(?:evolution|production|generation)?\s*rates?", N + r"\s*" + _H2U),
            GUARD + N + r"\s*" + _H2U,
        ]},
    "degradation": {
        "name": "degradation efficiency", "unit": "%", "better": "max", "range": (0, 100),
        "apps": ["dye degradation", "photocatalytic degradation", "dye removal"],
        "patterns": [
            _kw(r"(?:dye |photocatalytic |photo )?degradation\s*(?:efficiency|rate)?", N + PC),
            GUARD + N + PC + r"[^.\n]{0,40}?degraded",
        ]},
    "ionic_conductivity": {
        "name": "ionic conductivity", "unit": "S cm-1", "better": "max", "range": (1e-9, 1),
        "apps": ["electrolyte", "solid electrolyte", "ionic conductor"],
        "patterns": [
            _kw(r"ionic conductivit(?:y|ies)", _SCOND),
            GUARD + _SCOND,
        ]},
    "tensile": {
        "name": "tensile strength", "unit": "MPa", "better": "max", "range": (0, 15000),
        "apps": ["mechanical", "fiber", "fibre", "film"],
        "patterns": [
            _kw(r"tensile strengths?", N + r"\s*(?:[GMk]\s*)?Pa\b"),
            _kw(r"\bUTS\b", N + r"\s*(?:[GMk]\s*)?Pa\b"),
        ]},
    "mobility": {
        "name": "charge carrier mobility", "unit": "cm2 V-1 s-1", "better": "max", "range": (0, 2000),
        "apps": ["transistor", "OFET", "field-effect"],
        "patterns": [
            _kw(r"(?:hole |electron |field-effect |field effect )?mobility",
                N + r"\s*" + _ug(r"[Cc][Mm]\s*\^?\s*[2²]", r"[Vv](?:olts?)?", r"[Ss](?:econds?)?")),
            GUARD + N + r"\s*" + _ug(r"[Cc][Mm]\s*\^?\s*[2²]", r"[Vv](?:olts?)?", r"[Ss](?:econds?)?"),
        ]},
    "tof": {
        "name": "turnover frequency", "unit": "h-1", "better": "max", "range": (0, 1e8),
        "apps": ["catalysis", "catalytic"],
        "patterns": [
            _kw(r"(?:turnover frequenc(?:y|ies)|TOFs?)\b", N + r"\s*[HhSs](?:ours?|econds?)?" + SEP),
        ]},
}

# how to normalise a unit spelling to the metric's base unit: (regex on the
# matched text, factor). Checked in order; the first hit wins.
_SCALES: dict[str, list[tuple[str, float]]] = {
    "overpotential": [(r"m\s*[Vv]", 1.0), (r"[Vv]", 1000.0)],
    "h2_rate": [(r"mmol", 1000.0), (r"[µμu]mol|umol", 1.0), (r"mol", 1e6)],
    "ionic_conductivity": [(r"milli\s*S|m\s*S", 1e-3), (r"[µμu]\s*S|uS", 1e-6), (r"n\s*S", 1e-9), (r"S", 1.0)],
    "tensile": [(r"G\s*Pa", 1000.0), (r"k\s*Pa", 0.001), (r"Pa", 1.0)],
    "tof": [(r"[Ss](?:econds?)?\s*[−–^/-]", 3600.0), (r"h", 1.0)],
}

_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")


def _number(raw: str, better: str) -> float | None:
    """Parse the captured token: commas, ranges, ×10^ exponents."""
    s = re.sub(r"[−–—]", "-", raw.translate(_SUP)).replace(" ", "").lower()
    exp = 0
    m = re.search(r"[×x]10\^?([-+]?\d+)$", s)
    if m:
        exp, s = int(m.group(1)), s[: m.start()]
    parts = [t for t in re.split(r"[-~]|to", s) if t]
    try:
        vals = [float(t.replace(",", "")) for t in parts[:2]]
    except ValueError:
        return None
    return (max(vals) if better == "max" else min(vals)) * 10 ** exp


def _snippet(text: str, m: re.Match) -> str:
    a, b = max(0, m.start() - 70), min(len(text), m.end() + 70)
    s = text[a:b]
    if a > 0 and s and not s[0].isspace() and " " in s:   # don't start mid-word
        s = re.sub(r"^\S+\s+", "", s, count=1)
    if b < len(text) and s and not s[-1].isspace() and " " in s.strip():   # nor end mid-word
        s = re.sub(r"\s+\S+$", "", s, count=1)
    return re.sub(r"\s+", " ", s).strip()[:160]


def _scale(key: str, matched: str) -> float:
    for pat, factor in _SCALES.get(key, []):
        if re.search(pat, matched, re.I):
            return factor
    return 1.0


def extract(text: str, key: str) -> list[dict]:
    """All sane values of metric `key` reported in `text`, with a short snippet each."""
    met = METRICS[key]
    lo, hi = met["range"]
    out, seen = [], set()
    for pat in met["patterns"]:
        for m in re.finditer(pat, text, re.I):
            v = _number(m.group(1), met["better"])
            if v is None:
                continue
            v *= _scale(key, m.group(0))
            if not (lo < v <= hi) or round(v, 9) in seen:
                continue
            seen.add(round(v, 9))
            out.append({"value": v, "snippet": _snippet(text, m)})
    return out


def _matcher(keyword: str) -> re.Pattern:
    t = re.escape(keyword)
    if keyword.endswith("y"):   # battery -> batteries
        t += f"(?:{re.escape(keyword[:-1])}ies|es|s)?"
    else:
        t += r"(?:es|s)?"
    return re.compile(r"\b" + t + r"\b", re.I)


def pick(application: str) -> str | None:
    """The metric for an application string: longest matching keyword wins."""
    best, best_len = None, 0
    for key, met in METRICS.items():
        for kw in met["apps"]:
            if _matcher(kw).search(application) and len(kw) > best_len:
                best, best_len = key, len(kw)
    return best
