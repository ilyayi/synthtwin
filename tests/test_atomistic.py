"""Atomistic study package: literature table, MD summaries, derived physics
overrides. No LAMMPS needed."""
import csv
import json
import math

import numpy as np
import pytest

from synthtwin.lib.atomistic import derive, literature as L, md, params as Pa

REQ = ("id", "quantity", "material", "value", "unit", "uncertainty", "method", "conditions", "citation", "verified")


def test_literature_entries_well_formed():
    ents = L.load()
    assert len(ents) >= 80
    ids = [e["id"] for e in ents]
    assert len(ids) == len(set(ids))
    for e in ents:
        for k in REQ:
            assert k in e, (e["id"], k)
        assert e["quantity"] in L.QUANTITIES
        assert e["material"] in ("Au", "Ag")
        assert e["citation"] and len(e["citation"]) > 20


def test_literature_query_and_combine():
    au = L.query("surface_energy_avg", "Au")
    assert {e["id"] for e in au} >= set(derive.GAMMA_LIT["Au"])
    v, u = L.combine(derive.GAMMA_LIT["Au"])
    assert 1.3 < v < 1.5 and 0.05 < u < 0.2
    assert "doi:" in L.cite("tysonmiller77_Au_avg") or "Tyson" in L.cite("tysonmiller77_Au_avg")
    with pytest.raises(KeyError):
        L.by_id("nope")


@pytest.mark.parametrize("m", ["Au", "Ag"])
@pytest.mark.parametrize("c", [None, "none", "citrate", "tannic", "pvp", "ctab"])
def test_overrides_well_formed(m, c):
    p = Pa.physics_overrides(m, c)
    names = set(Pa.NAMES) if c is not None else set(Pa.NAMES) - {"capping_dG_eV", "ligand_shell_nm"}
    assert names <= set(p)
    for k in names:
        assert isinstance(p[k], float) and math.isfinite(p[k])
        assert p["_uncertainty"][k] >= 0
        assert p["_sources"][k] and all(isinstance(s, str) for s in p["_sources"][k])
        assert p["_grade"][k] in ("strong", "moderate", "weak")
    s = Pa.physics_overrides(m, c, strip=True)
    assert not any(k.startswith("_") for k in s)


@pytest.mark.parametrize("m", ["Au", "Ag"])
def test_override_ranges(m):
    for c in Pa.CAPPINGS:
        p = Pa.physics_overrides(m, c, strip=True)
        assert 0.8 < p["gamma_J_m2"] < 1.6
        assert 1.0e-5 < p["Vm_m3_mol"] < 1.04e-5
        assert 0.0 <= p["coalescence_dmax_nm"] < 20
        assert 0.0 < p["coalescence_eff"] <= 1.0
        assert -1.5 < p["capping_dG_eV"] <= 0.0
        assert 0.0 < p["ligand_shell_nm"] < 6
    # capping lowers gamma (Gibbs adsorption); none is the bare value
    g = {c: Pa.physics_overrides(m, c, strip=True)["gamma_J_m2"] for c in Pa.CAPPINGS}
    assert all(g[c] <= g["none"] for c in Pa.CAPPINGS)


def test_overrides_aliases_and_errors():
    a = Pa.physics_overrides("au", "Tannic Acid", strip=True)
    assert a == Pa.physics_overrides("Au", "tannic", strip=True)
    with pytest.raises(ValueError):
        Pa.physics_overrides("Cu")
    with pytest.raises(ValueError):
        Pa.physics_overrides("Au", "oleylamine")


def test_overrides_accepted_by_simulator_names():
    """The six names are the simulator's override names."""
    assert Pa.NAMES == ("gamma_J_m2", "Vm_m3_mol", "coalescence_dmax_nm", "coalescence_eff",
                        "capping_dG_eV", "ligand_shell_nm")


def _rows(name):
    with (derive.DATA / name).open() as fh:
        return list(csv.DictReader(fh))


def test_md_bulk_slab_matches_foiles():
    b = json.loads((derive.DATA / "md_bulk_slab.json").read_text())
    assert b["Au"]["ecoh_eV"] == pytest.approx(-3.93, abs=0.01)
    assert b["Ag"]["ecoh_eV"] == pytest.approx(-2.85, abs=0.01)
    for m in ("Au", "Ag"):  # EAM ordering (111) < (100) < (110)
        assert b[m]["gamma_111_J_m2"] < b[m]["gamma_100_J_m2"] < b[m]["gamma_110_J_m2"]
    assert b["Au"]["gamma_111_J_m2"] == pytest.approx(0.79, abs=0.03)


def test_md_clusters_capillarity():
    rows = _rows("md_clusters.csv")
    assert len(rows) >= 16
    for m in ("Au", "Ag"):
        r = [x for x in rows if x["material"] == m]
        g = np.array([float(x["gamma_GT_J_m2"]) for x in r if float(x["d_nominal_nm"]) >= 2])
        # size dependence of the cluster surface energy is small (< 3 %)
        assert np.ptp(g) / g.mean() < 0.03


def test_md_melting_depression():
    rows = _rows("md_melting.csv")
    for m in ("Au", "Ag"):
        r = sorted(((float(x["d_eq_nm"]), float(x["Tm_K"])) for x in rows
                    if x["material"] == m and x["Tm_K"] and float(x["d_nominal_nm"]) >= 2))
        assert len(r) >= 4
        T = [t for _, t in r]
        assert all(b > a for a, b in zip(T, T[1:]))  # Tm rises with size
        pw = derive.pawlow(m)
        assert 1000 < pw["Tm_bulk_K"] < 1400 and 0.3 < pw["alpha_nm"] < 1.5


def test_md_coalescence_present():
    rows = _rows("md_coalescence.csv")
    for m in ("Au", "Ag"):
        r = [x for x in rows if x["material"] == m]
        assert len({x["d_nm"] for x in r}) >= 4
        assert len({x["T_K"] for x in r}) >= 2
        # contact always lowers the energy (neck formation)
        assert all(float(x["dPE_eV_atom"]) < 0 for x in r)


def test_fuchs_no_barrier_for_small_clusters():
    W, vmax = derive.fuchs_W(1e-9, 2.5e-19, -0.03, 1e-3)
    assert 0.3 < W < 2.0 and vmax < 3
    # a large, highly charged particle in dilute salt is stabilised
    W2, vmax2 = derive.fuchs_W(10e-9, 1e-19, -0.06, 1e-4)
    assert W2 > 100 and vmax2 > 10


def test_gibbs_adsorption_sign():
    assert derive.gibbs_adsorption("none", "Au") == (0.0, 0.0)
    v, u = derive.gibbs_adsorption("citrate", "Au")
    assert -0.15 < v < 0 and u > 0


def test_md_driver_parses_without_lammps(tmp_path):
    ap = md.build_parser() if hasattr(md, "build_parser") else None
    if ap is None:
        pytest.skip("no parser factory")
    a = ap.parse_args(["--lmp", "lmp", "--stage", "analyze", "--rundir", str(tmp_path)])
    assert a.stage == "analyze"


def test_helps_steep_nucleation_keeps_onset():
    """The steep-nucleation variant raises the barrier and the CNT prefactor
    together, so ln J at the onset is unchanged."""
    from synthtwin.lib.atomistic import helps
    s = helps.STEEP
    assert s["nuc_barrier_ref_kT"] > 30
    assert s["log10_nuc_prefactor"] * math.log(10) - s["nuc_barrier_ref_kT"] == pytest.approx(30 * math.log(10) - 30)
    assert len(helps.CASES) == 7 and helps.CASES[helps.ANCHOR][0].startswith("Au citrate 3.5")


def test_md_coalescence_grid_complete():
    rows = _rows("md_coalescence.csv")
    cut = [x for x in rows if x["start"] == "as-cut"]
    assert len(cut) >= 150 and len([x for x in rows if x["start"] == "annealed"]) >= 30
    for m in ("Au", "Ag"):
        sizes = sorted({float(x["d_nm"]) for x in cut if x["material"] == m})
        assert sizes[0] == 1.5 and sizes[-1] >= 8
        # residual elongation after the run grows with size (300 K, as-cut, 2 ns runs)
        xi = [np.mean([float(x["xi_final"]) for x in cut if x["material"] == m and float(x["d_nm"]) == d
                       and x["T_K"] == "300"]) for d in (1.5, 3.0, 6.0)]
        assert xi[0] < xi[1] < xi[2]
