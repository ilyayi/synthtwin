"""split_sweep_gold tests: anchor selection, card/vault contents, canary."""
from __future__ import annotations

import re

import pytest

from synthtwin.lib.sweep import split_sweep_gold
from synthtwin.lib.vault import _number_pattern

from conftest import load_sweep_gold


def test_anchor_is_median_odd_n(sweep_a):
    card, _ = sweep_a
    # sorted ratios [1, 2.5, 5, 10, 20] -> middle is 5
    assert card.anchor_label == "r5"
    assert {o.quantity: o.value for o in card.anchor_outcomes} == {
        "size_mean_nm": 18.0,
        "size_cv_pct": 19.0,
    }


def test_anchor_is_lower_median_even_n(sweep_b):
    card, _ = sweep_b
    # sorted pH [4, 6, 8, 10] -> lower median is 6
    assert card.anchor_label == "pH6"
    assert card.anchor_outcomes[0].value == 32.0


def test_anchor_three_points(sweep_c):
    card, _ = sweep_c
    assert card.anchor_label == "s0.010"
    assert card.anchor_outcomes[0].value == 30.0


def test_card_holds_no_measured_secrets(sweep_a):
    card, vault = sweep_a
    blob = card.model_dump_json()
    assert "measured" not in blob
    assert "canary" not in blob
    assert "digitised" not in blob
    # held-out values must not leak into the card in their measured spelling
    # (the anchor 18.0 / 19.0 are public); boundary-aware so "9.0" does not
    # count as a match inside the public "19.0"
    for label, outcomes in vault.outcomes.items():
        if label == card.anchor_label:
            continue
        for o in outcomes:
            assert not _number_pattern(f"{o.value:.1f}", False).search(blob), o.value


def test_vault_holds_all_points_and_canary(sweep_a):
    card, vault = sweep_a
    assert list(vault.outcomes) == ["r1", "r2p5", "r5", "r10", "r20"]
    assert [o.value for o in vault.outcomes["r1"]] == [42.0, 28.0]
    assert vault.digitised_by == ["erin", "farid"]
    assert re.fullmatch(r"[0-9a-f]{16}", vault.canary)


def test_deterministic_split(sweep_a):
    card1, _ = sweep_a
    card2, _ = split_sweep_gold(load_sweep_gold("np-au-citrate-a"))
    assert card1 == card2


def test_canary_stable_when_rebuilt():
    gold = load_sweep_gold("np-au-ph-b")
    _, vault1 = split_sweep_gold(gold, existing_canary="cafe1234cafe1234")
    assert vault1.canary == "cafe1234cafe1234"


def test_canary_random_when_new():
    gold = load_sweep_gold("np-au-ph-b")
    _, v1 = split_sweep_gold(gold)
    _, v2 = split_sweep_gold(gold)
    assert v1.canary != v2.canary


def test_missing_anchor_measurement_raises():
    gold = load_sweep_gold("np-ag-seed-c")
    del gold["measured"]["s0.010"]  # the would-be anchor
    with pytest.raises(ValueError, match="s0.010"):
        split_sweep_gold(gold)
