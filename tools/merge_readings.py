"""Merge two blinded readings (A, B) into gold JSON. Points kept only if both readers
gave T50 and |A-B| <= 10 K; gold T50 = mean, unc = max(reader unc, |A-B|/2).
Card fields come from A; disagreements on card fields are listed for a human.
Usage: python merge_readings.py <readings_dir> <gold_dir>   (prints a report, no T50 values)"""
import json, sys
from pathlib import Path

TOL = 10.0
CARD_KEYS = ["sweep_variable", "catalyst_mass_mg", "flow_ml_min", "ghsv_per_h", "ramp_K_min"]


def norm(label):
    return "".join(label.lower().split())


CATALYST_KEYS = {"metal", "support", "loading_wt_pct", "particle_nm", "dispersion", "prep"}


def fit_catalyst(point):
    """Keep the schema's Catalyst fields; fold any extra reader fields (per-sample
    mass, at% or g/ft3 loading, ...) into the prep text so nothing is lost."""
    cat = dict(point["catalyst"])
    extra = {k: cat.pop(k) for k in list(cat) if k not in CATALYST_KEYS}
    extra = {k: v for k, v in extra.items() if v is not None}
    if extra:
        note = "; ".join(f"{k}={v}" for k, v in extra.items())
        cat["prep"] = (cat.get("prep") or "") + f" [also reported: {note}]"
    return {**point, "catalyst": cat}


def main(rd, gd):
    rd, gd = Path(rd), Path(gd)
    for fa in sorted((rd / "A").glob("*.json")):
        fb = rd / "B" / fa.name
        slug = fa.stem
        if not fb.exists():
            print(f"{slug}: no B reading"); continue
        a, b = json.loads(fa.read_text()), json.loads(fb.read_text())
        if a.get("usable") is False or b.get("usable") is False:
            print(f"{slug}: marked unusable (A={a.get('usable')}, B={b.get('usable')})"); continue
        diffs = [k for k in CARD_KEYS if a.get(k) != b.get(k)]
        for k in ("co_pct", "o2_pct"):
            if (a.get("feed") or {}).get(k) != (b.get("feed") or {}).get(k):
                diffs.append(f"feed.{k}")
        mb = {norm(m["label"]): m for m in b.get("measured", []) if m.get("t50_K") is not None}
        kept, dropped = [], []
        for m in a.get("measured", []):
            o = mb.get(norm(m["label"]))
            if m.get("t50_K") is None or o is None:
                dropped.append(f"{m['label']}(unmatched)"); continue
            d = abs(m["t50_K"] - o["t50_K"])
            if d > TOL:
                dropped.append(f"{m['label']}(disagree {d:.0f}K)"); continue
            kept.append({"label": m["label"], "t50_K": round((m["t50_K"] + o["t50_K"]) / 2, 1),
                         "t50_unc_K": round(max(m.get("t50_unc_K") or 5, o.get("t50_unc_K") or 5, d / 2), 1),
                         "curve": m.get("curve") or [], "source": m.get("source") or a.get("figure") or ""})
        # a point with no value of the swept variable (e.g. an uncalcined reference
        # in a calcination series) is not part of the sweep
        unswept = {p["label"] for p in a["points"] if p.get("value") is None}
        dropped += [f"{l}(no sweep value)" for l in sorted(unswept)]
        kept = [k for k in kept if k["label"] not in unswept]
        labels = {k["label"] for k in kept}
        pts = [fit_catalyst(p) for p in a["points"] if p["label"] in labels]
        status = "OK" if len(kept) >= 3 else "TOO FEW"
        print(f"{slug}: {status} kept {len(kept)}/{len(a.get('measured', []))}; dropped {dropped}; card diffs {diffs}")
        if status != "OK":
            continue
        gold = {k: a.get(k) for k in ["case_id", "paper_title", "paper_url", "licence", "published", "post_cutoff",
                                       "sweep_variable", "feed", "catalyst_mass_mg", "flow_ml_min", "ghsv_per_h",
                                       "ramp_K_min", "missing"]}
        gold["case_id"] = slug
        gold["post_cutoff"] = bool(gold["post_cutoff"])
        gold["missing"] = gold["missing"] or []
        gold["points"], gold["measured"] = pts, kept
        gold["digitised_by"] = ["reader-A", "reader-B"]
        (gd / f"{slug}.json").write_text(json.dumps(gold, indent=1))
        (gd.parent / "review" / f"{slug}.json").write_text(json.dumps({"card_field_disagreements": diffs, "dropped": dropped}))


if __name__ == "__main__":
    main(*sys.argv[1:3])
