"""Sweep vault: sealed write/read permissions and the general leak scan."""
from __future__ import annotations

import stat

from synthtwin.core.schemas import SweepVault
from synthtwin.lib.sweep import held_out_values, leak_scan
from synthtwin.lib.vault import read_sealed, write_sealed


def test_write_sealed_permissions(sweep_a, tmp_path):
    _card, vault = sweep_a
    vdir = tmp_path / "vault"
    path = write_sealed(vdir, vault)
    assert stat.S_IMODE(vdir.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.name == "np-au-citrate-a.json"


def test_read_sealed_roundtrip(sweep_a, tmp_path):
    _card, vault = sweep_a
    vdir = tmp_path / "vault"
    path = write_sealed(vdir, vault)
    assert read_sealed(vdir, SweepVault, vault.case_id) == vault
    assert read_sealed(path, SweepVault) == vault


def test_held_out_values_cover_all_quantities_not_anchor(sweep_a):
    card, vault = sweep_a
    assert sorted(held_out_values(vault, card.anchor_label)) == [
        9.0, 12.5, 14.0, 16.0, 23.0, 28.0, 28.5, 42.0,
    ]
    # with a wrong anchor label the public values appear too
    assert 18.0 in held_out_values(vault, "r1")


def test_leak_scan_clean_file(tmp_path, sweep_a):
    _card, vault = sweep_a
    values = held_out_values(vault, "r5")
    f = tmp_path / "notes.md"
    f.write_text("agent notes: predicted size near 15 nm, nothing secret\n")
    assert leak_scan([f], "deadbeefdeadbeef", values) == []


def test_leak_scan_finds_canary(tmp_path, sweep_a):
    _card, vault = sweep_a
    values = held_out_values(vault, "r5")
    f = tmp_path / "notes.md"
    f.write_text("agent notes deadbeefdeadbeef oops\n")
    assert leak_scan([f], "deadbeefdeadbeef", values) == [
        f"{f}: contains the vault canary"
    ]


def test_leak_scan_finds_three_values_across_quantities(tmp_path, sweep_a):
    """2 sizes + 1 cv value from the held-out points is already a leak."""
    _card, vault = sweep_a
    f = tmp_path / "report.md"
    f.write_text("sizes 42.0 and 28.5 nm, cv 23.0 % - looks like the paper\n")
    hits = leak_scan([f], "canary123", held_out_values(vault, "r5"))
    assert len(hits) == 1
    assert "3 held-out values" in hits[0]


def test_leak_scan_below_threshold(tmp_path, sweep_a):
    _card, vault = sweep_a
    f = tmp_path / "report.md"
    f.write_text("saw 42.0 and 28.5 nm somewhere\n")  # only 2 values
    assert leak_scan([f], "canary123", held_out_values(vault, "r5")) == []


def test_leak_scan_finds_celsius_free_integer_forms(tmp_path, sweep_a):
    """No K/degC shift here: the plain integer spellings are what must match."""
    _card, vault = sweep_a
    f = tmp_path / "scratch.txt"
    f.write_text("integers 42 and 9 and 14 look familiar\n")
    hits = leak_scan([f], "canary123", held_out_values(vault, "r5"))
    assert len(hits) == 1


def test_leak_scan_ignores_neighbouring_numbers(tmp_path):
    f = tmp_path / "scratch.txt"
    # 142.0 / 42.05 / 42.00 / 142 are not 42.0
    f.write_text("neighbours 142.0, 42.05, 42.00, 142 stay clean\n")
    assert leak_scan([f], "canary123", [42.0, 43.0, 44.0]) == []


def test_leak_scan_skips_missing_paths(tmp_path, sweep_a):
    _card, vault = sweep_a
    assert leak_scan([tmp_path / "nope.md"], "canary123",
                     held_out_values(vault, "r5")) == []
