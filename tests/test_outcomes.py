"""Outcome mining: sizes with sd, method attribution from nearby words,
LSPR peaks, DLS values, and the near-misses that must stay unparsed."""
from __future__ import annotations

import pytest

from synthtwin.lib.recipes.outcomes import parse_outcomes


def outcomes(texts):
    return {o.quantity: o for o in parse_outcomes([("abstract", t) for t in texts])}


def test_size_with_sd_and_method():
    found = outcomes(["Au nanoparticles of 15 ± 2 nm were observed by TEM."])
    assert found["size_mean_nm"].value == 15.0
    assert found["size_sd_nm"].value == 2.0
    assert found["size_mean_nm"].method == "TEM"
    assert found["size_mean_nm"].source == "abstract"


@pytest.mark.parametrize(
    "text,mean",
    [
        ("The average particle size was 20 nm.", 20.0),
        ("average diameter of 12.4 ± 1.3 nm (DLS)", 12.4),
        ("TEM showed 5 nm gold nanoparticles.", 5.0),
        ("particles averaged 10 nm", 10.0),
        ("nanocrystals with a diameter of 7.5 nm", 7.5),
    ],
)
def test_size_phrasings(text, mean):
    assert outcomes([text])["size_mean_nm"].value == pytest.approx(mean)


@pytest.mark.parametrize(
    "text",
    [
        "A 0.5 nm chromium layer was deposited.",       # layer thickness
        "Irradiated at 441.6 nm with an argon laser.",  # laser line
        "Diluted to 100 nmol per litre.",               # not a size
        "The 25 mL round flask was heated.",            # not nm at all
    ],
)
def test_size_not_a_size(text):
    assert "size_mean_nm" not in outcomes([text])


def test_sd_stated_separately():
    found = outcomes(["The mean size was 18 nm with a standard deviation of 3 nm."])
    assert found["size_mean_nm"].value == 18.0
    assert found["size_sd_nm"].value == 3.0


def test_first_statement_wins():
    found = outcomes(["Small 5 nm particles formed; after growth the average "
                      "particle size was 30 nm."])
    assert found["size_mean_nm"].value == 5.0


def test_lspr():
    found = outcomes(["UV-visible absorption band at 410 nm."])
    assert found["lspr_nm"].value == 410.0
    found = outcomes(["the surface plasmon resonance peak at 520 nm confirmed Au"])
    assert found["lspr_nm"].value == 520.0
    # abstracts wrap lines mid-sentence; the gap may span a newline
    found = outcomes(["showed the surface plasmon\nresonance peak at 410 nm"])
    assert found["lspr_nm"].value == 410.0
    # a wavelength without a plasmon/absorption word nearby is not an LSPR
    assert "lspr_nm" not in outcomes(["excited at 532 nm with no absorption stated."])


def test_dls_and_pdi():
    found = outcomes(["Hydrodynamic diameter of 28 nm with PDI of 0.21 (DLS)."])
    assert found["dls_z_nm"].value == 28.0
    assert found["dls_pdi"].value == 0.21
    # hydrodynamic size is not the TEM size
    assert "size_mean_nm" not in found


def test_cv_pct():
    found = outcomes(["Particle size 10 nm with a coefficient of variation of 12%."])
    assert found["size_cv_pct"].value == 12.0


def test_abstract_beats_steps():
    found = {o.quantity: o for o in parse_outcomes([
        ("abstract", "Au nanoparticles of 15 ± 2 nm."),
        ("step 1", "Mix and heat; particles of 40 nm formed later.")])}
    assert found["size_mean_nm"].value == 15.0
    assert found["size_mean_nm"].source == "abstract"
