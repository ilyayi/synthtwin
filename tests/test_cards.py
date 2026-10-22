"""cards.split_gold tests: anchor selection, card/vault contents, canary."""
from __future__ import annotations

import re

from synthtwin.lib.cards import split_gold

from conftest import load_gold


def test_anchor_is_median_odd_n(case_a):
    card, _ = case_a
    # sorted values [0.1, 0.5, 1.0, 2.0, 5.0] -> middle is 1.0
    assert card.anchor_label == "1.0Pt"
    assert card.anchor_t50_K == 440.0


def test_anchor_is_lower_median_even_n(case_b):
    card, _ = case_b
    # sorted values [2, 5, 10, 20] -> lower median is 5
    assert card.anchor_label == "5nm-Pd"
    assert card.anchor_t50_K == 445.0


def test_anchor_three_points(case_c):
    card, _ = case_c
    assert card.anchor_label == "D50"
    assert card.anchor_t50_K == 455.0


def test_card_holds_no_measured_secrets(case_a):
    card, vault = case_a
    blob = card.model_dump_json()
    assert "measured" not in blob
    assert "canary" not in blob
    assert "digitised" not in blob
    # held-out T50s must not leak into the card (the anchor 440.0 is public)
    for m in vault.points:
        if m.label == card.anchor_label:
            continue
        assert f"{m.t50_K:g}" not in blob


def test_vault_holds_all_points_and_canary(case_a):
    card, vault = case_a
    assert [p.label for p in vault.points] == [
        "0.1Pt", "0.5Pt", "1.0Pt", "2.0Pt", "5.0Pt",
    ]
    assert [p.t50_K for p in vault.points] == [520.0, 470.5, 440.0, 415.0, 395.0]
    assert vault.digitised_by == ["alice", "bob"]
    assert re.fullmatch(r"[0-9a-f]{16}", vault.canary)


def test_deterministic_split(case_a):
    card1, _ = case_a
    card2, vault2 = split_gold(load_gold("co-pt-loading-a"))
    assert card1 == card2
    assert vault2.canary  # fresh canary generated


def test_canary_stable_when_rebuilt():
    gold = load_gold("co-pd-particle-b")
    _, vault1 = split_gold(gold, existing_canary="cafe1234cafe1234")
    assert vault1.canary == "cafe1234cafe1234"


def test_canary_random_when_new():
    gold = load_gold("co-pd-particle-b")
    _, v1 = split_gold(gold)
    _, v2 = split_gold(gold)
    assert v1.canary != v2.canary
