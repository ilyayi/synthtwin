"""Generate examples/recipes.jsonl: 12 synthetic Turkevich-style Au recipes.

Run once from the repo root to refresh the file:

    nice -n 19 .venv/bin/python tools/gen_example_recipes.py

Numbers come from the made-up size law in the docstring (a cousin of the test
stub's law, so calibration has a small real scale ~0.93 and a few percent
spread). Every recipe states it is synthetic; never present these as real data.
"""
from __future__ import annotations

import json
from pathlib import Path

# (ratio citrate:Au, temperature_C, conc_precursor_mM, time_min, vol_ml, rpm)
ROWS = [
    (2.0, 90.0, 0.50, 30.0, 100.0, 600.0),
    (3.0, 90.0, 0.50, 30.0, 100.0, 600.0),
    (3.5, 80.0, 0.30, 45.0, 50.0, 400.0),
    (4.0, 100.0, 0.25, 20.0, 100.0, 700.0),
    (3.0, 70.0, 0.50, 60.0, 50.0, 300.0),
    (5.0, 95.0, 0.75, 25.0, 20.0, 500.0),
    (2.5, 85.0, 1.00, 40.0, 50.0, 500.0),
    (6.0, 100.0, 0.50, 15.0, 100.0, 700.0),
    (4.5, 75.0, 0.40, 50.0, 20.0, 350.0),
    (7.0, 90.0, 0.60, 30.0, 50.0, 600.0),
    (3.5, 100.0, 0.35, 20.0, 100.0, 650.0),
    (5.5, 80.0, 0.25, 45.0, 50.0, 450.0),
]


def library_size_nm(ratio: float, temp: float, conc: float) -> float:
    """Made-up 'published' size law: close to the stub's but not identical."""
    return 42.0 * ratio ** -0.72 * (temp / 100.0) ** -1.45 * (conc / 0.5) ** 0.12


def library_cv_pct(temp: float) -> float:
    return 8.5 * (100.0 / temp) ** 1.45


def recipe(i: int, ratio: float, temp: float, conc: float, time: float, vol: float, rpm: float) -> dict:
    size = round(library_size_nm(ratio, temp, conc), 1)
    cv = round(library_cv_pct(temp), 1)
    return {
        "recipe_id": f"manual:np-example:{i:02d}",
        "source": "manual",
        "paper_title": "Synthetic Turkevich-style Au example (made-up numbers, not a real paper)",
        "paper_url": "",
        "published": "",
        "material": "Au",
        "method": "citrate reduction",
        "reagents": [
            {"role": "precursor", "name": "HAuCl4", "conc_mM": conc},
            {"role": "reductant", "name": "trisodium citrate", "conc_mM": round(conc * ratio, 2)},
            {"role": "solvent", "name": "water"},
        ],
        "conditions": {
            "temperature_C": temp,
            "time_min": time,
            "total_volume_ml": vol,
            "ratio_reductant_precursor": ratio,
            "conc_precursor_mM": conc,
            "stirring_rpm": rpm,
        },
        "steps": [
            f"Heat {vol:.0f} mL HAuCl4 solution ({conc:.2f} mM) to {temp:.0f} C with stirring at {rpm:.0f} rpm",
            f"Add trisodium citrate solution (molar ratio citrate:Au = {ratio:.1f}) rapidly",
            f"Keep at {temp:.0f} C for {time:.0f} min, then cool to room temperature",
        ],
        "outcomes": [
            {"quantity": "size_mean_nm", "value": size, "unit": "nm", "unc": 1.0,
             "method": "TEM", "basis": "number", "source": "synthetic example"},
            {"quantity": "size_cv_pct", "value": cv, "unit": "%", "unc": 1.0,
             "method": "TEM", "basis": "number", "source": "synthetic example"},
            {"quantity": "lspr_nm", "value": round(517.0 + 0.35 * size, 1), "unit": "nm",
             "unc": 2.0, "method": "UV-Vis", "source": "synthetic example"},
            {"quantity": "dls_z_nm", "value": round(1.12 * size, 1), "unit": "nm",
             "unc": 2.0, "method": "DLS", "basis": "intensity", "source": "synthetic example"},
        ],
        "missing": ["addition_rate_ml_min"],
        "extraction_score": 1.0,
    }


def main() -> None:
    out = Path(__file__).parent.parent / "examples" / "recipes.jsonl"
    lines = [json.dumps(recipe(i + 1, *row)) for i, row in enumerate(ROWS)]
    out.write_text("".join(line + "\n" for line in lines))
    print(f"wrote {len(lines)} synthetic recipes to {out}")


if __name__ == "__main__":
    main()
