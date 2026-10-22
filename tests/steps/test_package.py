"""The robot step's protocol package: generic across systems, built from the study only."""
from synthtwin.steps.robot import package


def _study():
    pb = {"material": "PMDA-ODA polyimide film", "method": "slot-die coating + thermal imidization",
          "targets": {"dry_thickness_um": {"value": 10.0}, "thickness_variation_pct": {"max": 3.0}},
          "knobs": {"coating_gap_um": [50, 300], "web_speed_m_min": [0.2, 3]},
          "fixed": {"imidization_final_T_C": 350.0}, "title": "10 um film"}
    p = {"id": "x-1", "method": pb["method"], "conditions": {"imidization_final_T_C": 350.0, "coating_gap_um": 186.5,
                                                            "web_speed_m_min": 0.21},
         "predicted": {"dry_thickness_um": {"value": 10.0, "low": 8.1, "high": 11.7, "unit": "um"}}}
    rc = {"title": "t", "steps": ["1. Set the slot-die gap to 186 µm.", "2. Soft-bake on a hot plate, then cure in an oven."],
          "checks": ["wet film 85-100 µm"]}
    return {"id": "x", "problem": pb}, {"study": "x", "proposal": p, "recipe": rc, "label": "exploratory"}


def test_units_and_labels_from_key_suffixes():
    assert package.unit("web_speed_m_min") == "m/min" and package.unit("solids_content_wt_pct") == "wt %"
    assert package.unit("imidization_final_T_C") == "°C" and package.unit("conc_precursor_mM") == "mM"
    assert package.label("coating_gap_um") == "coating gap"


def test_package_sections():
    s, req = _study()
    pk = package.build(s, req)
    assert [c["kind"] for c in pk["conditions"]] == ["varied", "varied", "fixed"]   # chosen knobs first
    assert pk["steps"][0] == "Set the slot-die gap to 186 µm."                    # numbering stripped
    assert any("slot-die" in e for e in pk["equipment"]) and any("oven" in e for e in pk["equipment"])
    assert pk["equipment_source"] == "from the steps"
    m = {x["quantity"]: x for x in pk["measurements"]}
    assert m["dry_thickness_um"]["instrument"].startswith("profilometer")
    assert m["thickness_variation_pct"]["target"] == {"max": 3.0} and m["thickness_variation_pct"]["predicted"] is None
    assert pk["acceptance"][0].startswith("dry thickness inside the predicted band") and "wet film 85-100 µm" in pk["acceptance"]


def test_recipe_lists_win():
    s, req = _study()
    req["recipe"].update(materials=[{"name": "PAA in NMP", "amount": "100 g", "role": "precursor"}],
                         equipment=["slot-die coater"])
    pk = package.build(s, req)
    assert pk["materials"][0]["name"] == "PAA in NMP" and pk["equipment"] == ["slot-die coater"]
    assert pk["materials_source"] == pk["equipment_source"] == "recipe"
