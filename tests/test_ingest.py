"""End-to-end ingestion from a tiny synthetic parquet fixture (made-up
numbers, no real data): row filtering, reagent roles, conditions, outcomes,
deduplication on (doi, material, method)."""
from __future__ import annotations

import pytest

pyarrow = pytest.importorskip("pyarrow")  # optional extra `data`

from synthtwin.lib.recipes.ingest import (  # noqa: E402
    is_colloidal_np, lematsynth, to_C, to_min,
)

STEP_CONDITIONS = {
    "temperature": None, "temp_unit": None, "duration": None, "time_unit": None,
    "pressure": None, "pressure_unit": None, "atmosphere": None,
    "stirring": None, "stirring_speed": None, "ph": None,
}


def _mat(name, amount=None, unit=None, purity=None):
    return {"vendor": None, "name": name, "amount": amount, "unit": unit,
            "purity": purity}


def _step(n, action, description, materials=(), **conditions):
    return {"step_number": n, "action": action, "description": description,
            "materials": [_mat(m) for m in materials], "equipment": [],
            "conditions": {**STEP_CONDITIONS, **conditions}}


def citrate_au_row(doi="10.1/au", abstract="Au nanoparticles of 15 ± 2 nm by TEM."):
    """Turkevich-style: boiling HAuCl4 + citrate, sizes in the abstract."""
    return {
        "synthesized_material": "Au nanoparticles",
        "material_category": "nanomaterials",
        "synthesis_method": "precipitation",
        "structured_synthesis": {
            "target_compound": "Au nanoparticles",
            "starting_materials": [
                _mat("Hydrogen tetrachloroauric acid trihydrate", 1.0, "mM"),
                _mat("Trisodium citrate", 10.0, "mL", "38.8 mM"),
                _mat("Milli-Q water", 90.0, "mL"),
            ],
            "steps": [
                _step(1, "heat", "Bring the gold solution to boiling.",
                      ["Hydrogen tetrachloroauric acid trihydrate"],
                      temperature=100.0, temp_unit="C", stirring=True, stirring_speed=800.0),
                _step(2, "add", "Add citrate; boil 15 min until wine-red.",
                      ["Trisodium citrate"],
                      temperature=100.0, temp_unit="C", duration=15.0, time_unit="min"),
            ],
            "notes": "Turkevich synthesis.",
        },
        "evaluation": {"scores": {"overall_score": 4.2}},
        "paper_title": "Citrate gold", "paper_doi": doi, "paper_url": "http://x/au",
        "paper_abstract": abstract, "paper_published_date": "2019-05-01",
    }


def seed_au_row(doi="10.2/seed"):
    """Seeded growth: NaBH4 seed step, ascorbic acid growth."""
    return {
        "synthesized_material": "Au nanorods",
        "material_category": "nanomaterials",
        "synthesis_method": "solution-based",
        "structured_synthesis": {
            "starting_materials": [
                _mat("Gold (III) chloride trihydrate", 0.25, "mL", "10 mM"),
                _mat("Sodium borohydride", 0.3, "mL", "10 mM"),
                _mat("CTAB", 10.0, "mL", "100 mM"),
                _mat("L-ascorbic acid", 1.0, "mL", "100 mM"),
            ],
            "steps": [
                _step(1, "mix", "Inject ice-cold NaBH4 into CTAB + HAuCl4 to make seeds.",
                      ["Sodium borohydride"], temperature=4.0, temp_unit="C",
                      stirring=True, stirring_speed=1200.0),
                _step(2, "mix", "Grow: add HAuCl4 and ascorbic acid to CTAB, add seeds.",
                      ["Gold (III) chloride trihydrate", "L-ascorbic acid"],
                      duration=12.0, time_unit="h", ph=3.2),
            ],
        },
        "evaluation": {"scores": {"overall_score": 3.0}},
        "paper_title": "Seeded rods", "paper_doi": doi, "paper_url": "http://x/ag",
        "paper_abstract": "Au nanorods of 25 ± 4 nm by TEM; plasmon band at 520 nm.",
        "paper_published_date": "2021",
    }


@pytest.fixture
def parquet(tmp_path):
    rows = [
        citrate_au_row(),
        citrate_au_row(),                      # exact duplicate -> dropped
        citrate_au_row(abstract="Another run, 40 nm particles."),  # same doi+material+method -> dropped
        seed_au_row(),
        {  # physical method -> dropped
            "synthesized_material": "Ag nanoparticles",
            "material_category": "nanomaterials",
            "synthesis_method": "PVD",
            "structured_synthesis": {"starting_materials": [], "steps": []},
            "evaluation": {}, "paper_title": "Sputtered", "paper_doi": "10.3/pvd",
            "paper_url": "", "paper_abstract": "", "paper_published_date": "",
        },
        {  # not a nanoparticle -> dropped
            "synthesized_material": "Pt/Al2O3 catalyst",
            "material_category": "functional materials & catalysts",
            "synthesis_method": "impregnation",
            "structured_synthesis": {"starting_materials": [], "steps": []},
            "evaluation": {}, "paper_title": "Catalyst", "paper_doi": "10.4/cat",
            "paper_url": "", "paper_abstract": "", "paper_published_date": "",
        },
        {  # a characterization row: nano material but no synthesis chemistry -> dropped
            "synthesized_material": "single-walled carbon nanotubes",
            "material_category": "nanomaterials",
            "synthesis_method": "other",
            "structured_synthesis": {
                "starting_materials": [_mat("SWCNT powder"), _mat("toluene")],
                "steps": [_step(1, "measure", "Measure magnetic susceptibility.")],
            },
            "evaluation": {}, "paper_title": "Susceptibility", "paper_doi": "10.5/swcnt",
            "paper_url": "", "paper_abstract": "", "paper_published_date": "",
        },
    ]
    import pyarrow as pa
    import pyarrow.parquet as pq
    table = pa.Table.from_pylist(rows)
    path = tmp_path / "fixture.parquet"
    pq.write_table(table, path)
    return path


def test_unit_conversions():
    assert to_C(25.0, "C") == 25.0
    assert to_C(373.15, "K") == pytest.approx(100.0)
    assert to_C(None, "C") is None
    assert to_min(90.0, "s") == pytest.approx(1.5)
    assert to_min(2.0, "h") == pytest.approx(120.0)
    assert to_min(1.0, "days") == pytest.approx(1440.0)
    assert to_min(None, "h") is None


def test_is_colloidal_np(parquet):
    import pyarrow.parquet as pq
    rows = pq.read_table(parquet).to_pylist()
    keep = [is_colloidal_np(r) for r in rows]
    # the characterization row still passes the name/method filter; the
    # chemistry-reagent requirement in _row_recipe is what drops it
    assert keep == [True, True, True, True, False, False, True]


def test_lematsynth_filters_dedups_and_parses(parquet):
    stats: dict = {}
    recipes = lematsynth([str(parquet)], stats)
    assert stats["rows_read"] == 7
    assert stats["kept"] == 2
    assert stats["duplicates"] == 2
    assert len(recipes) == 2
    ids = sorted(r.recipe_id for r in recipes)
    assert ids == ["lematsynth:10.1/au:0", "lematsynth:10.2/seed:0"]

    au = next(r for r in recipes if r.material == "Au" and r.method == "citrate reduction")
    roles = {reagent.role: reagent for reagent in au.reagents}
    assert set(roles) == {"precursor", "reductant", "solvent"}
    assert roles["reductant"].conc_mM == pytest.approx(38.8)
    assert roles["reductant"].volume_ml == pytest.approx(10.0)
    assert au.conditions["temperature_C"] == pytest.approx(100.0)
    assert au.conditions["time_min"] == pytest.approx(15.0)
    assert au.conditions["stirring_rpm"] == pytest.approx(800.0)
    # citrate moles 0.388 mmol in 100 mL -> 3.88 mM final; ratio vs 1 mM stock
    assert au.conditions["conc_reductant_mM"] == pytest.approx(3.88, rel=1e-3)
    assert au.conditions["total_volume_ml"] == pytest.approx(100.0)
    quantities = {o.quantity: o.value for o in au.outcomes}
    assert quantities["size_mean_nm"] == 15.0
    assert quantities["size_sd_nm"] == 2.0
    assert "pH" in au.missing and "ratio_reductant_precursor" in au.missing
    assert au.extraction_score == 4.2
    assert au.published == "2019-05-01"
    assert au.steps and au.steps[0].startswith("1. heat:")

    rods = next(r for r in recipes if r.method == "seeded growth")
    quantities = {o.quantity: o.value for o in rods.outcomes}
    assert quantities["size_mean_nm"] == 25.0
    assert quantities["size_sd_nm"] == 4.0
    assert quantities["lspr_nm"] == 520.0
    assert rods.conditions["time_min"] == pytest.approx(720.0)
    assert rods.conditions["pH"] == pytest.approx(3.2)
    assert rods.conditions["temperature_C"] == pytest.approx(4.0)
    # moles from conc x volume for both -> ratio computable
    # red: 0.3 mL x 10 mM + 1 mL x 100 mM = 0.103 mmol; prec: 0.25 mL x 10 mM
    assert rods.conditions["ratio_reductant_precursor"] == pytest.approx(0.103 / 0.0025, rel=1e-3)


def test_seed_row_roles(parquet):
    recipes = lematsynth([str(parquet)])
    rods = next(r for r in recipes if r.method == "seeded growth")
    roles = sorted(reagent.role for reagent in rods.reagents)
    assert roles == ["capping", "precursor", "reductant", "reductant"]
