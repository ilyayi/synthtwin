"""Chemistry helpers for recipe ingestion: material names, reagent roles,
amounts and moles.

Called by synthtwin.lib.recipes.ingest (row -> Recipe) and novelty (reagent-name
comparison). Nothing here reads files; every function is pure text in ->
structured value out, and unknown inputs stay None/"".
"""
from __future__ import annotations

import re

ELEMENTS = set(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni "
    "Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe "
    "Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au "
    "Hg Tl Pb Bi Po Th U".split()
)

# element names written out in material strings -> symbol ("gold nanoparticles")
ELEMENT_NAMES = {
    "gold": "Au", "silver": "Ag", "platinum": "Pt", "palladium": "Pd",
    "copper": "Cu", "iron": "Fe", "cobalt": "Co", "nickel": "Ni", "zinc": "Zn",
    "cadmium": "Cd", "selenium": "Se", "tellurium": "Te", "titanium": "Ti",
    "zirconium": "Zr", "cerium": "Ce", "lead": "Pb", "tin": "Sn",
    "bismuth": "Bi", "indium": "In", "antimony": "Sb", "tungsten": "W",
    "molybdenum": "Mo", "rhodium": "Rh", "ruthenium": "Ru", "iridium": "Ir",
}

# common lab/material words that are not reagents even when LeMat-Synth lists
# them as starting materials (glassware, substrates, gases)
JUNK_RE = re.compile(
    r"wafer|glass|slide|coverslip|substrate|latex|polystyrene sphere|"
    r"template|membrane|filter|crucible|stir bar|nitrogen|argon|ambient|"
    r"atmosphere|oxygen gas|\bn2\b|\bar\b|\bo2\b|carbon electrode|dry ice|ice\b",
    re.I,
)

_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_FORMULA_CHUNK = re.compile(r"([A-Z][a-z]?\d*(?:\.\d+)?)")

# canonical-name synonyms: regex (lowercase) -> replacement, applied in order
_SYNONYMS = [
    (r"gold\s*\(?\s*(?:iii|3\+)?\s*\)?\s*chloride(?:\s*trihydrate)?", "haucl4"),
    (r"(?:hydrogen\s+)?tetrachloroauric\s+acid|(?:hydrogen\s+)?tetrachloroaurate"
     r"(?:\s+tri?hydrate)?|chloroauric\s+acid", "haucl4"),
    (r"silver\s+nitrate", "agno3"),
    (r"sodium\s+borohydride", "nabh4"),
    (r"potassium\s+borohydride", "kbh4"),
    (r"(?:tri(?:basic)?|di)?(?:\s*sodium|\s*potassium)?\s*citrate"
     r"(?:\s+(?:di|mono)hydrate)?", "citrate"),
    (r"(?:l-)?ascorbic\s+acid|sodium\s+ascorbate", "ascorbic acid"),
    (r"poly[\s-]?vinyl[\s-]?pyrrolidone|\bpvp\b", "pvp"),
    (r"(?:1-)?(?:cetyl|hexadecyl)[\s)-]*trimethylammonium\s+bromide|\bctab\b",
     "ctab"),
    (r"(?:1-)?(?:cetyl|hexadecyl)[\s)-]*trimethylammonium\s+chloride|\bctac\b",
     "ctac"),
    (r"polyethylene\s+glycol|\bpeg\b", "peg"),
    (r"milli-?q\s+water|deionised\s+water|deionized\s+water|distilled\s+water|"
     r"\bdi\s+water|ultra-?purified\s+water|millipore\s+water", "water"),
]

# role rules: regex over the canonical name, first match wins ("seed" beats
# "precursor" because a seed solution often contains the precursor salt)
ROLE_RULES = [
    ("seed", r"\bseed"),
    ("precursor",
     r"haucl4|aucl3|agno3|silver\s+acetate|silver\s+perchlorate|silver\s+carbonate|"
     r"silver\s+sulfate|silver\s+trifluoroacetate|gold\s+acetate|palladium\s+nitrate|"
     r"pdcl2|palladium\s+chloride|h2ptcl6|chloroplatinic|platinum\s+chloride|"
     r"ptcl2|potassium\s+chloroplatinate"),
    ("reductant",
     r"nabh4|kbh4|citrate|citric\s+acid|ascorbic\s+acid|hydrazine|formaldehyde|"
     r"sodium\s+formate|formic\s+acid|glucose|fructose|sucrose|tannic|tannin|"
     r"ethylene\s+glycol|diethylene\s+glycol|propylene\s+glycol|glycerol|"
     r"sodium\s+dithionite|dopamine|hydroquinone|extract"),
    ("capping",
     r"pvp|ctab|ctac|trimethylammonium|oleylamine|oleic\s+acid|oleate|thiol|"
     r"mercapto|\bpeg\b|pluronic|\bsds\b|sodium\s+dodecyl|dodecyl|chitosan|"
     r"starch|gelatin|alginate|albumin|glutathione|hexadecylamine|tetraoctyl|"
     r"didodecyldimethylammonium|brij|tween|triton|lignin|humic|cysteine|"
     r"peptide|protein|\bdna\b|\brna\b|polyacrylate|cyclodextrin"),
    ("base",
     r"\bnaoh\b|sodium\s+hydroxide|\bkoh\b|potassium\s+hydroxide|ammonia|"
     r"ammonium\s+hydroxide|\bnh4oh\b|sodium\s+carbonate|\bna2co3\b|\burea\b"),
    ("acid",
     r"\bhcl\b|hydrochloric|\bhno3\b|nitric\s+acid|\bh2so4\b|sulfuric\s+acid|"
     r"acetic\s+acid"),
    ("solvent",
     r"\bwater\b|ethanol|methanol|isopropanol|toluene|chloroform|"
     r"dichloromethane|\bdmf\b|\bdmso\b|\bthf\b|acetonitrile|benzyl\s+alcohol|"
     r"hexane|octadecene|acetone"),
]

# (keyword in canonical name, [(hydrate keyword, g/mol), ..., (default,)])
MOLAR_MASS = [
    ("haucl4", [("trihydrate", 393.83), ("", 339.79)]),
    ("agno3", [("", 169.87)]),
    ("nabh4", [("", 37.83)]),
    ("kbh4", [("", 53.94)]),
    ("citrate", [("dihydrate", 294.10), ("", 258.06)]),
    ("citric acid", [("monohydrate", 210.14), ("", 192.12)]),
    ("ascorbic acid", [("", 176.12)]),
    ("ctab", [("", 364.45)]),
]


def canon_name(name: str) -> str:
    """Reagent name -> canonical lowercase name: synonyms collapsed
    ('trisodium citrate dihydrate' -> 'citrate', 'PVP' -> 'pvp')."""
    t = (name or "").translate(_SUBSCRIPTS).strip().rstrip(".,;").lower()
    t = " ".join(re.sub(r"[()\[\]{}]", " ", t).split())
    t = " ".join(t.split())
    for pattern, replacement in _SYNONYMS:
        t = re.sub(pattern, replacement, t)
        t = " ".join(t.split())
    return t.lower()


def _is_formula_word(word: str) -> bool:
    """A whole token like 'Fe3O4', 'CdSe' or 'Au' whose element chunks are all
    real element symbols."""
    w = re.sub(r"(?:NPs?|QDs?)$", "", word)
    if not w or not re.fullmatch(r"(?:[A-Z][a-z]?\d*(?:\.\d+)?)+", w):
        return False
    chunks = _FORMULA_CHUNK.findall(w)
    return all(c.rstrip("0123456789.") in ELEMENTS for c in chunks)


def material_elements(material: str) -> set[str]:
    """Element symbols in a parsed material ('Ag-Au' -> {'Ag', 'Au'},
    'Fe3O4' -> {'Fe', 'O'}); the fallback-precursor exclusion is applied by
    the caller."""
    out = set()
    for chunk in _FORMULA_CHUNK.findall(material or ""):
        sym = chunk.rstrip("0123456789.")
        if sym in ELEMENTS:
            out.add(sym)
    return out


def parse_material(text: str) -> str | None:
    """'Au nanoparticles', 'Trisoctahedral (TOH) Gold Nanocrystals',
    'citrate-capped gold nanoparticles (Au NPs)' -> 'Au'; 'Ag-Au alloy
    nanoparticles' -> 'Ag-Au'; 'CdSe quantum dots' -> 'CdSe'. Shape words,
    parentheticals and descriptors are dropped. Materials with no chemical
    token keep their descriptive name ('graphene quantum dots' -> 'graphene');
    None when nothing remains."""
    if not text:
        return None
    t = (text.translate(_SUBSCRIPTS).replace("(", " ").replace(")", " "))
    tokens = []
    for word in re.split(r"[^A-Za-z0-9.]+", t):
        if not word or word == ".":
            continue
        if _is_formula_word(word.strip(".")):
            tokens.append(re.sub(r"(?:NPs?|QDs?)$", "", word.strip(".")))
        else:
            low = word.lower().strip(".")
            if low in ELEMENT_NAMES:
                tokens.append(ELEMENT_NAMES[low])
    # unique, order kept ('Ag-Au alloy' stays 'Ag-Au')
    seen, uniq = set(), []
    for tok in tokens:
        if tok not in seen:
            seen.add(tok)
            uniq.append(tok)
    if uniq:
        return "-".join(uniq[:3])
    cleaned = _SHAPE_RE.sub(" ", t.lower()).strip(" -@.,")
    cleaned = " ".join(cleaned.split())[:40]
    return cleaned or None


_SHAPE_RE = re.compile(
    r"nano\w*|particles?|colloidal|colloids?|clusters?|quantum\s+dots?|\bQDs?\b|"
    r"\bNPs?\b|spheres?|spherical|monodisperse|uniform|dots?|rods?|wires?|"
    r"tubes?|stars?|cubes?|cages?|flowers?|sheets?|plates?|frames?|capped|"
    r"functionalized|synthesized|shaped|hierarchical|hierarchically|structured|"
    r"single-? ?(?:wall|walled)|multi-? ?(?:wall|walled)|chirality|chiral|"
    r"enantiomer|semiconducting|metallic|metallic-enriched|\b[mpn]-doped\b|"
    r"hole-doped|oxygen-doped|nitrogen-doped|oxygen-defect|\d+(?:\.\d+)?\s*,\s*\d+(?:\.\d+)?",
    re.I)


# a reagent that is itself a nanoparticle of the target material: a purchased
# or pre-made suspension used to seed growth, not a precursor salt
_NP_NAME_RE = re.compile(
    r"nano\w+|\bNPs?\b|\bQDs?\b|quantum\s?dot", re.I)


def role_of(name: str, material: str = "") -> str:
    """Reagent name -> role via the dictionary; a salt of the target material
    falls back to 'precursor' ('Palladium(II) acetylacetonate' for Pd), and a
    nanoparticle suspension of it to 'seed' ('Au nanosphere solution')."""
    canon = canon_name(name)
    for role, pattern in ROLE_RULES:
        if re.search(pattern, canon):
            return role
    if material and _NP_NAME_RE.search(name):
        symbols = material_elements(material) - {"C", "H", "N", "O", "S", "Cl"}
        low = canon
        for symbol in symbols:
            if re.search(rf"(?<![a-z0-9]){symbol.lower()}(?![a-z0-9])", low):
                return "seed"
        for word, symbol in ELEMENT_NAMES.items():
            if symbol in symbols and re.search(rf"\b{word}\b", low):
                return "seed"
    if material:
        symbols = material_elements(material) - {"C", "H", "N", "O", "S", "Cl"}
        low = canon
        for symbol in symbols:
            if re.search(rf"(?<![a-z0-9]){symbol.lower()}(?![a-z0-9])", low):
                return "precursor"
        for word, symbol in ELEMENT_NAMES.items():
            if symbol in symbols and re.search(rf"\b{word}\b", low):
                return "precursor"
    return "other"


_CONC_UNITS = {"mm": 1.0, "mmol/l": 1.0, "mmol l-1": 1.0, "um": 1e-3, "m": 1e3,
               "mol/l": 1e3, "mol l-1": 1e3}
_VOL_UNITS = {"ml": 1.0, "l": 1e3, "ul": 1e-3}
_CONC_IN_TEXT = re.compile(
    r"(\d+(?:\.\d+)?)\s*(mM|mmol/L|mmol L-1|uM|mol/L|mol L-1|M)\b")


def parse_amount(amount, unit: str, purity: str = "") -> tuple[float | None, float | None, str]:
    """(conc_mM, volume_ml, amount_str) from a structured starting-material
    entry: 'mL' -> volume, 'mM'/'M' -> concentration (also read from the
    purity field, which LeMat-Synth uses for stock molarity); anything else
    keeps only the written amount string."""
    conc = vol = None
    a = None
    if amount is not None:
        try:
            a = float(amount)
        except (TypeError, ValueError):
            a = None
    u = (unit or "").strip().replace("µ", "u").replace("μ", "u").lower()
    if a is not None:
        if u in _VOL_UNITS:
            vol = a * _VOL_UNITS[u]
        elif u in _CONC_UNITS:
            conc = a * _CONC_UNITS[u]
    if conc is None and purity:
        m = _CONC_IN_TEXT.search(str(purity).replace("µ", "u"))
        if m:
            factor = _CONC_UNITS.get(m.group(2).lower())
            if factor:
                conc = float(m.group(1)) * factor
    amount_str = "" if a is None or not (unit or "").strip() else f"{amount:g} {unit}"
    return conc, vol, amount_str


def _molar_mass(canon: str, raw: str) -> float | None:
    low = (raw or "").lower()
    for keyword, entries in MOLAR_MASS:
        if keyword in canon:
            for hydrate, mass in entries:
                if not hydrate or hydrate in low:
                    return mass
    return None


def moles_mmol(canon: str, raw: str, conc_mM: float | None,
               volume_ml: float | None, amount, unit: str) -> float | None:
    """Millimoles of a reagent from conc x volume, or from a mass when the
    molar mass of the salt is known. None when it cannot be computed."""
    if conc_mM and volume_ml:
        return conc_mM * volume_ml / 1000.0
    u = (unit or "").strip().replace("µ", "u").replace("μ", "u").lower()
    if amount is None or u not in ("mg", "g"):
        return None
    try:
        a = float(amount)
    except (TypeError, ValueError):
        return None
    mass_g = a / 1000.0 if u == "mg" else a
    mw = _molar_mass(canon, raw)
    return mass_g / mw * 1000.0 if mw else None
