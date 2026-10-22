"""The SynthTwin screener: scan LeMat-Synth for reported bests worth beating.

index.py    build/load the compact jsonl index over the extracted syntheses
metrics.py  figures of merit: application keywords and number-extraction regexes
scan.py     the funnel, family ranking, labels and study texts; refine (deep pass)

Used through `python -m synthtwin.lib.screen` and by the UI server (/api/screen)."""
