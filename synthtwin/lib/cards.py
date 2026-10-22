"""Split a gold-case JSON into an agent-visible CaseCard and a vault entry.

Called by the synthtwin CLI (build) and by tests. The gold file has the
CaseCard fields (without anchor_*) plus `measured: [MeasuredPoint]` and
`digitised_by`. The anchor is the point whose swept value is the median
(lower median for even n) - deterministic, so the same gold file always
yields the same card. The card reveals only the anchor's T50; the vault
keeps every measurement plus the leak-scan canary.
"""
from __future__ import annotations

import secrets

from synthtwin.core.schemas import CaseCard, MeasuredPoint, SweepPoint, VaultEntry

# gold fields that go into the card (everything CaseCard accepts minus the
# anchor fields, which split_gold derives from the measured points)
CARD_FIELDS = set(CaseCard.model_fields) - {"anchor_label", "anchor_t50_K"}


def split_gold(
    gold: dict, existing_canary: str | None = None
) -> tuple[CaseCard, VaultEntry]:
    """Build (card, vault) from a gold dict.

    existing_canary: when rebuilding, pass the canary of the vault file that
    already exists for this case so canaries stay stable across rebuilds.
    """
    measured = [MeasuredPoint.model_validate(m) for m in gold["measured"]]
    by_label = {m.label: m for m in measured}
    points = [SweepPoint.model_validate(p) for p in gold["points"]]

    # anchor = median swept value (lower median for even n); label breaks ties
    ordered = sorted(points, key=lambda p: (float(p.value), str(p.label)))
    anchor = ordered[(len(ordered) - 1) // 2]
    if anchor.label not in by_label:
        raise ValueError(
            f"gold case {gold.get('case_id')!r}: no measured point for "
            f"anchor label {anchor.label!r}"
        )

    card = CaseCard(
        **{k: v for k, v in gold.items() if k in CARD_FIELDS},
        anchor_label=anchor.label,
        anchor_t50_K=by_label[anchor.label].t50_K,
    )
    vault = VaultEntry(
        case_id=card.case_id,
        points=measured,
        digitised_by=list(gold["digitised_by"]),
        canary=existing_canary or secrets.token_hex(8),
    )
    return card, vault
