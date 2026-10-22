#!/bin/sh
# Literature optimisation campaigns for the 60/40 benchmark (bench6040.py).
# MIT licence, PV-Lab/Benchmarking; Liang et al., npj Comput Mater 7, 188 (2021).
#   https://github.com/PV-Lab/Benchmarking
# Usage: fetch_bench_data.sh [DEST_DIR]   (default: bench-data next to the repo)
set -e
dest="${1:-bench-data}"
mkdir -p "$dest"
base="https://raw.githubusercontent.com/PV-Lab/Benchmarking/main"
# remote file names differ from the local short names bench6040.py expects
curl -fsSL -o "$dest/AgNP.csv"          "$base/datasets/AgNP_dataset.csv"
curl -fsSL -o "$dest/AutoAM.csv"        "$base/datasets/AutoAM_dataset.csv"
curl -fsSL -o "$dest/Crossed_barrel.csv" "$base/datasets/Crossed%20barrel_dataset.csv"
curl -fsSL -o "$dest/P3HT.csv"          "$base/datasets/P3HT_dataset.csv"
curl -fsSL -o "$dest/Perovskite.csv"    "$base/datasets/Perovskite_dataset.csv"
curl -fsSL -o "$dest/LICENSE-PVLab-Benchmarking" "$base/LICENSE"
echo "5 datasets + licence -> $dest"
