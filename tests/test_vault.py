"""Vault write/read permissions and the leak scan."""
from __future__ import annotations

import stat

from synthtwin.lib.vault import leak_scan, read_vault, write_vault

HELD_OUT = [520.0, 470.5, 415.0, 395.0]  # case A measured, minus the anchor


def test_write_vault_permissions(case_a, tmp_path):
    _card, vault = case_a
    vdir = tmp_path / "vault"
    path = write_vault(vdir, vault)
    assert stat.S_IMODE(vdir.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.name == "co-pt-loading-a.json"


def test_read_vault_roundtrip(case_a, tmp_path):
    _card, vault = case_a
    vdir = tmp_path / "vault"
    path = write_vault(vdir, vault)
    assert read_vault(vdir, vault.case_id) == vault
    assert read_vault(path) == vault


def test_leak_scan_clean_file(tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("agent notes: simulated T50 near 450 K, nothing secret\n")
    assert leak_scan([f], "deadbeefdeadbeef", HELD_OUT) == []


def test_leak_scan_finds_canary(tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("agent notes, nothing to see\n")
    assert leak_scan([f], "deadbeefdeadbeef", HELD_OUT) == []
    f.write_text("agent notes deadbeefdeadbeef oops\n")
    assert leak_scan([f], "deadbeefdeadbeef", HELD_OUT) == [
        f"{f}: contains the vault canary"
    ]


def test_leak_scan_finds_three_kelvin_values(tmp_path):
    f = tmp_path / "report.md"
    f.write_text("maybe the values are 520.0, 470.5 and 395 K-ish\n")
    hits = leak_scan([f], "canary123", HELD_OUT)
    assert len(hits) == 1
    assert "3 held-out T50 values" in hits[0]


def test_leak_scan_below_threshold(tmp_path):
    f = tmp_path / "report.md"
    f.write_text("saw 520.0 and 470.5 somewhere\n")  # only 2 of 4 values
    assert leak_scan([f], "canary123", HELD_OUT) == []


def test_leak_scan_finds_celsius_and_integer_forms(tmp_path):
    f = tmp_path / "scratch.txt"
    c = [v - 273.15 for v in (520.0, 470.5, 415.0)]
    f.write_text(f"temps: {c[0]:.1f} C, {c[1]:.1f} C, {int(round(c[2]))} C\n")
    hits = leak_scan([f], "canary123", HELD_OUT)
    assert len(hits) == 1


def test_leak_scan_finds_integer_kelvin(tmp_path):
    f = tmp_path / "scratch.txt"
    f.write_text("integers 520 and 395 and 415 look familiar\n")
    hits = leak_scan([f], "canary123", HELD_OUT)
    assert len(hits) == 1


def test_leak_scan_ignores_neighbouring_numbers(tmp_path):
    f = tmp_path / "scratch.txt"
    # 1448.3 / 448.35 / 448.30 / 1448 are not 448.3 (or its C forms)
    f.write_text("neighbours 1448.3, 448.35, 448.30, 1448 and 455 stay clean\n")
    assert leak_scan([f], "canary123", [448.3, 448.4, 448.5]) == []


def test_leak_scan_skips_missing_paths(tmp_path):
    assert leak_scan([tmp_path / "nope.md"], "canary123", HELD_OUT) == []
