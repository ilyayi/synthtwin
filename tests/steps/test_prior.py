"""The prior step: benchmark cards become studies with sealed outcomes, and the
literature scout's extractions carry their provenance."""
from __future__ import annotations

from synthtwin.core.llm import Stub, _minimal
from synthtwin.steps.prior import prior

PB = {"material": "Au", "method": "citrate", "knobs": {"ratio_reductant_precursor": [1, 10]},
      "targets": {"size_mean_nm": {"value": 15}}}

CARD = {"case_id": "c1", "material": "Au", "method": "citrate reduction",
        "sweep_variable": "ratio_reductant_precursor", "quantities": ["size_mean_nm"],
        "anchor_label": "mid", "anchor_outcomes": [{"quantity": "size_mean_nm", "value": 18}],
        "points": [{"label": "mid", "value": 5, "conditions": {"ratio_reductant_precursor": 5}},
                   {"label": "hi", "value": 9, "conditions": {"ratio_reductant_precursor": 9}}]}


def test_benchmark_card_is_blind_except_the_anchor() -> None:
    (st,) = prior.from_cards(PB, [CARD])
    assert st["blind"] and st["source"] == "benchmark"
    states = {p["label"]: (p["outcomes"], p["state"]) for p in st["points"]}
    assert states["mid"] == ({"size_mean_nm": 18}, "anchor (visible)")
    assert states["hi"][0] is None and states["hi"][1].startswith("sealed")


def test_web_search_extracts_and_marks_provenance() -> None:
    def llm(system: str, prompt: str, schema: dict) -> dict:
        ans = _minimal(schema)
        ans.update(reply="r", studies=[{
            "title": "t", "url": "https://example.org/p", "swept_key": "temperature_C",
            "points": [{"swept_value": 90, "outcomes": [{"quantity": "size_mean_nm", "value": 12}]}],
            "takeaway": "hotter, smaller", "confidence": "high"}])
        return ans

    out, reply = prior.web_search(Stub(llm), PB)
    assert reply == "r" and out[0]["source"] == "web" and not out[0]["blind"]
    assert out[0]["points"][0]["outcomes"] == {"size_mean_nm": 12}
    assert "unverified" in out[0]["note"]
