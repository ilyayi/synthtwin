"""Nanoparticle simulator (synthtwin.lib.np): mass balance, optics checks, DLS,
qualitative literature trends, physics overrides, speed and loader
compatibility with synthtwin.lib.design and synthtwin.lib.sweep. Numbers are reported
in docs/reports/np-sim.md."""
from __future__ import annotations

import time

import numpy as np
import pytest

from synthtwin.lib.np import chemistry, growth, model, optics, params

FAMILIES = [("Au", "citrate"), ("Ag", "citrate"), ("Au", "hot_injection"), ("Au", "borohydride"),
            ("Ag", "borohydride"), ("Au", "seeded"), ("Ag", "seeded"), ("Au", "tannic"), ("Ag", "tannic")]


def nominal(material: str, method: str, **cond) -> dict:
    """One nominal simulator run (draw 0)."""
    run = chemistry.setup({"material": material, "method": method, "conditions": cond})
    res = growth.simulate(run, growth.nominal_draws(1))
    return {"d": float(res["mean_nm"][0]), "cv": float(res["cv_pct"][0]),
            "reduced": float(res["reduced_frac"][0]), "res": res}


@pytest.mark.parametrize("material,method", FAMILIES)
def test_mass_balance(material, method):
    run = chemistry.setup({"material": material, "method": method, "conditions": {}})
    res = growth.simulate(run, growth.random_draws(4, seed=1))
    assert res["mass_balance"]["rel_error"] < 1e-9
    assert np.all(res["reduced_frac"] > 0.5)


def single_peak(material: str, d_nm: float) -> float:
    p = params.get_params(material, "citrate")
    spec = optics.cext(material, np.array([d_nm]), optics.WAVELENGTHS_NM, p)
    return float(optics.peak(spec, material)[0][0])


@pytest.mark.parametrize("material,d,lo,hi", [("Au", 20, 518, 526), ("Au", 80, 545, 560), ("Ag", 20, 395, 410)])
def test_optics_checks(material, d, lo, hi):
    assert lo <= single_peak(material, d) <= hi


def test_mie_small_particle_limit():
    """Mie extinction of a 5 nm Au sphere matches the quasi-static dipole."""
    p = dict(params.get_params("Au", "citrate"), ligand_shell_nm=0.0)
    wl = np.array([450.0, 520.0, 600.0])
    c = optics.cext("Au", np.array([5.0]), wl, p)[0]
    eps = optics.eps_particle("Au", wl, np.array([2.5]), p)[0]
    em = 1.333 ** 2
    k = 2 * np.pi * 1.333 / (wl * 1e-9)
    alpha = 4 * np.pi * (2.5e-9) ** 3 * (eps - em) / (eps + 2 * em)
    assert np.allclose(c, k * alpha.imag, rtol=0.03)


def test_dls_z_above_number_mean():
    for material, method in [("Au", "citrate"), ("Au", "borohydride"), ("Ag", "seeded")]:
        out = model.predict({"material": material, "method": method, "conditions": {}, "n_draws": 4})
        assert out["dls_z_nm"]["value"] > out["size_mean_nm"]["value"]
        assert 0 <= out["dls_pdi"]["value"] < 0.5


def test_turkevich_ratio_trend():
    """Size falls as citrate:Au goes ~1 -> ~4, then levels off (Frens 1973)."""
    d = {r: nominal("Au", "citrate", ratio_reductant_precursor=r, time_min=30)["d"] for r in (1, 2, 3.5, 5, 10)}
    assert d[1] > d[2] > d[3.5]
    assert d[1] > 1.4 * d[3.5]
    assert d[10] >= 0.85 * d[5]                        # levels: < 15 % change from 5 to 10
    assert d[3.5] - d[10] < 0.3 * (d[1] - d[3.5])


def test_higher_temperature_smaller_narrower():
    lo = nominal("Au", "citrate", temperature_C=80, time_min=90)
    hi = nominal("Au", "citrate", temperature_C=100, time_min=90)
    assert hi["d"] < lo["d"]
    assert hi["cv"] < lo["cv"]


@pytest.mark.parametrize("material", ["Au", "Ag"])
def test_borohydride_small(material):
    bh = nominal(material, "borohydride")["d"]
    cit = nominal(material, "citrate")["d"]
    assert bh < 6.0
    assert bh < cit


@pytest.mark.parametrize("material,ratio", [("Ag", 0.005), ("Ag", 0.02), ("Au", 0.5), ("Au", 1.0)])
def test_seeded_volume_scaling(material, ratio):
    r = nominal(material, "seeded", ratio_seed_precursor=ratio)
    d_seed = params.get_params(material, "seeded")["default_seed_d_nm"]
    expected = d_seed * (1 + r["reduced"] / ratio) ** (1 / 3)
    assert r["d"] == pytest.approx(expected, rel=0.06)


def test_seeded_injections_grow():
    one = nominal("Au", "seeded", n_injections=1)["d"]
    three = nominal("Au", "seeded", n_injections=3, conc_precursor_mM=0.5)["d"]
    assert three > one


def test_tannic_more_ta_smaller():
    d = [nominal("Au", "tannic", conc_capping_mM=c)["d"] for c in (0.0025, 0.01, 0.05)]
    assert d[0] > d[1] > d[2]
    assert 3.0 < d[2] and d[0] < 12.0


def test_base_changes_citrate_rate():
    run_a = chemistry.setup({"material": "Au", "method": "citrate", "conditions": {}})
    run_b = chemistry.setup({"material": "Au", "method": "citrate", "conditions": {"conc_base_mM": 0.5}})
    assert run_b.pH > run_a.pH
    k_a = growth._reductant_table(run_a)[0]["k1"]
    k_b = growth._reductant_table(run_b)[0]["k1"]
    assert k_a != pytest.approx(k_b, rel=0.05)


def test_physics_overrides():
    p = params.get_params("Au", "citrate")
    src = params.sources("Au", "citrate")
    for name in params.PHYSICS_NAMES:
        assert name in p and src[name]
    base = model.predict({"material": "Au", "method": "citrate", "conditions": {}, "n_draws": 1})
    off = model.predict({"material": "Au", "method": "citrate", "conditions": {}, "n_draws": 1,
                         "physics": {"coalescence_dmax_nm": 0}})
    assert off["size_mean_nm"]["value"] < base["size_mean_nm"]["value"]
    shell = model.predict({"material": "Au", "method": "citrate", "conditions": {}, "n_draws": 1,
                           "physics": {"ligand_shell_nm": 5.0}})
    assert shell["dls_z_nm"]["value"] > base["dls_z_nm"]["value"] + 6
    capped = model.predict({"material": "Au", "method": "citrate", "conditions": {}, "n_draws": 1,
                            "physics": {"capping_dG_eV": -0.6}})
    assert capped["size_mean_nm"]["value"] != pytest.approx(base["size_mean_nm"]["value"], rel=0.01)


def test_predict_bands_and_speed():
    t0 = time.perf_counter()
    out = model.predict({"material": "Au", "method": "citrate", "conditions": {}})
    assert time.perf_counter() - t0 < 3.0
    assert set(out) == set(model.QUANTITIES)
    for band in out.values():
        assert band["low"] <= band["value"] <= band["high"]
    again = model.predict({"material": "Au", "method": "citrate", "conditions": {}})
    assert again == out                                    # seeded ensemble


def test_spectrum():
    s = model.spectrum({"material": "Au", "method": "citrate", "conditions": {}, "n_draws": 2})
    assert len(s["wavelength_nm"]) == len(s["absorbance"])
    assert 515 < s["lspr_nm"] < 530 and max(s["absorbance"]) > 0.1


def test_calibrate_recovers_size():
    p = {"material": "Au", "method": "citrate", "conditions": {"ratio_reductant_precursor": 3.5}}
    cal = model.calibrate(p, {"size_mean_nm": 18.0})
    assert set(cal) == {"log10_growth_scale"}
    out = model.predict({**p, "calibration": cal, "n_draws": 1})
    assert out["size_mean_nm"]["value"] == pytest.approx(18.0, rel=0.05)


def test_calibrate_seeded_two_quantities():
    p = {"material": "Ag", "method": "seeded", "conditions": {"ratio_seed_precursor": 0.01}}
    cal = model.calibrate(p, {"size_mean_nm": 30.0, "dls_z_nm": 35.0})
    assert set(cal) == {"log10_seed_scale", "log10_growth_scale"}
    out = model.predict({**p, "calibration": cal, "n_draws": 1})
    assert out["size_mean_nm"]["value"] == pytest.approx(30.0, rel=0.08)


def test_design_and_sweep_loaders(sweep_a):
    from synthtwin.lib.design.run import load_predictor
    from synthtwin.core.schemas import Outcome
    from synthtwin.lib.sweep import load_sweep_model, model_predict

    mod = load_predictor("synthtwin.lib.np.model")
    cal = mod.calibrate({"material": "Au", "method": "citrate reduction", "conditions": {}},
                        [Outcome(quantity="size_mean_nm", value=15.0, unit="nm")])
    assert "log10_growth_scale" in cal
    predict, calibrate = load_sweep_model("synthtwin.lib.np.model:make_model")
    card, _ = sweep_a
    pred = model_predict(card, predict, calibrate)
    sizes = [pred.points[p.label]["size_mean_nm"].value for p in card.points]
    assert all(np.isfinite(sizes))
    predict_ag, _ = load_sweep_model("synthtwin.lib.np.model:ag")
    assert predict_ag({"ratio_seed_precursor": 0.01, "temperature_C": 25.0})["lspr_nm"]["value"] < 480
