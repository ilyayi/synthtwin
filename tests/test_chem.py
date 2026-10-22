"""Parsing unit tests: material names, canonical reagent names, roles,
amounts and moles."""
from __future__ import annotations

import pytest

from synthtwin.lib.recipes.chem import (
    canon_name, moles_mmol, parse_amount, parse_material, role_of,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Au nanoparticles", "Au"),
        ("Gold Nanoparticles (Au NPs)", "Au"),
        ("Trisoctahedral (TOH) Gold Nanocrystals", "Au"),
        ("citrate-capped gold nanoparticles", "Au"),
        ("AuNPs", "Au"),
        ("Ag-Au alloy nanoparticles", "Ag-Au"),
        ("Pt/Au core-shell nanoparticles", "Pt-Au"),
        ("Ag nanotips", "Ag"),
        ("silver nanowires", "Ag"),
        ("CdSe quantum dots", "CdSe"),
        ("CdSe/ZnS core-shell quantum dots", "CdSe-ZnS"),
        ("Fe3O4 nanoparticles", "Fe3O4"),
        ("TiO2 nanoparticles", "TiO2"),
        ("ZnO nanorods", "ZnO"),
        ("graphene quantum dots", "graphene"),
        ("carbon dots", "carbon"),
    ],
)
def test_parse_material(text, expected):
    assert parse_material(text) == expected


@pytest.mark.parametrize("text", ["", "nanoparticles", "quantum dots"])
def test_parse_material_nothing_left(text):
    assert parse_material(text) in (None, "")


def test_canon_name_synonyms():
    assert canon_name("Trisodium citrate dihydrate") == "citrate"
    assert canon_name("Sodium citrate") == "citrate"
    assert canon_name("L-ascorbic acid") == "ascorbic acid"
    assert canon_name("Polyvinylpyrrolidone") == "pvp"
    assert canon_name("Poly Vinyl Pyrrolidone") == "pvp"  # spaced spelling
    assert canon_name("(1-Hexadecyl) trimethylammonium chloride") == "ctac"
    assert canon_name("CTAB") == "ctab"
    assert canon_name("Gold (III) chloride trihydrate") == "haucl4"
    assert canon_name("Silver nitrate") == "agno3"
    assert canon_name("Sodium borohydride") == "nabh4"
    assert canon_name("Milli-Q water") == "water"


@pytest.mark.parametrize(
    "name,material,role",
    [
        ("Gold (III) chloride trihydrate", "Au", "precursor"),
        ("Silver nitrate", "Ag", "precursor"),
        ("Palladium(II) acetylacetonate", "Pd", "precursor"),  # element fallback
        ("Sodium borohydride", "Au", "reductant"),
        ("Trisodium citrate", "Au", "reductant"),
        ("L-ascorbic acid", "Au", "reductant"),
        ("PVP", "Au", "capping"),
        ("CTAB", "Au", "capping"),
        ("(1-Hexadecyl) trimethylammonium chloride", "Au", "capping"),
        ("Oleylamine", "Au", "capping"),
        ("Milli-Q water", "Au", "solvent"),
        ("Sodium hydroxide", "Au", "base"),
        ("Au seed solution", "Au", "seed"),   # seed beats precursor
        ("Au nanosphere solution", "Au", "seed"),  # NP suspension, not a salt
        ("gold nanorods", "Au", "seed"),
        ("Ethanol", "Au", "solvent"),
        ("Latex spheres", "Au", "other"),
    ],
)
def test_role_of(name, material, role):
    assert role_of(name, material) == role


def test_parse_amount_units():
    assert parse_amount(1.0, "mM") == (1.0, None, "1 mM")
    assert parse_amount(0.1, "M") == (100.0, None, "0.1 M")
    assert parse_amount(250.0, "uM") == (0.25, None, "250 uM")
    assert parse_amount(25.0, "mL") == (None, 25.0, "25 mL")
    assert parse_amount(750.0, "µL") == (None, 0.75, "750 µL")
    assert parse_amount(0.025, "L") == (None, 25.0, "0.025 L")
    # molarity hiding in the purity field
    assert parse_amount(0.025, "L", "0.1 M") == (100.0, 25.0, "0.025 L")
    assert parse_amount(10.0, "mL", "38.8 mM") == (38.8, 10.0, "10 mL")
    # unconvertible units keep only the written amount
    assert parse_amount(5.0, "mg") == (None, None, "5 mg")
    assert parse_amount("excess", "wt%") == (None, None, "")
    assert parse_amount(None, None) == (None, None, "")


def test_moles_mmol():
    # conc x volume: 25 mM x 10 mL = 0.25 mmol
    assert moles_mmol("citrate", "trisodium citrate", 25.0, 10.0, None, "") == pytest.approx(0.25)
    # mass with known molar mass: 5 mg NaBH4 / 37.83 g/mol = 0.1322 mmol
    assert moles_mmol("nabh4", "Sodium borohydride", None, None, 5.0, "mg") == pytest.approx(0.1322, rel=1e-3)
    # hydrate awareness: 5 mg HAuCl4·3H2O uses 393.83
    assert moles_mmol("haucl4", "Gold(III) chloride trihydrate", None, None, 5.0, "mg") == pytest.approx(0.0127, rel=1e-3)
    # unknown molar mass stays unknown
    assert moles_mmol("pvp", "PVP", None, None, 5.0, "mg") is None
    assert moles_mmol("ctab", "CTAB", None, None, 5.0, "mg") == pytest.approx(0.01372, abs=2e-5)
