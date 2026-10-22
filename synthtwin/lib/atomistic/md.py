"""LAMMPS EAM driver for the atomistic study (Au, Ag).

Runs the input templates in ``lammps/`` and summarises results into small
CSV/JSON files under ``data/``. Raw trajectories and LAMMPS logs go to a run
directory (default ``build/atomistic_runs``) that is kept out of git.

Potentials: Foiles, Baskes & Daw, Phys. Rev. B 33, 7983 (1986), "universal 3"
funcfl files ``Au_u3.eam`` / ``Ag_u3.eam`` shipped in the LAMMPS ``potentials/``
directory (pass ``--potdir`` or set ``LAMMPS_POTENTIALS``).

Usage (each stage is restartable; finished jobs are skipped)::

    python -m synthtwin.lib.atomistic.md --lmp /path/to/lmp --potdir /path/to/potentials \
        --stage all [--gpus 0,1 --jobs-per-gpu 2]
    python -m synthtwin.lib.atomistic.md --stage analyze     # no LAMMPS needed

GPU runs use the KOKKOS package (``-k on g 1 -sf kk``); without ``--gpus`` the
plain CPU build is used. A watchdog pauses (SIGSTOP) LAMMPS when any GPU reaches
``--tmax`` (default 83 C) and resumes below ``--tmax - 8``.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import collections
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TDIR = HERE / "lammps"
DATA = HERE / "data"
EV_A2_TO_J_M2 = 16.02176634
NA = 6.02214076e23

MATERIALS = {
    # mass (amu), starting lattice guess (A), potential file
    "Au": {"mass": 196.97, "a_guess": 4.08, "pot": "Au_u3.eam", "dt": 0.004},
    "Ag": {"mass": 107.87, "a_guess": 4.09, "pot": "Ag_u3.eam", "dt": 0.003},
}
CLUSTER_D_NM = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
MELT_D_NM = [1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0]
COAL_D_NM = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0]
COAL_T_K = [300, 373, 450, 550]
# orientation (x, y, z) and periodic lengths along x, y, z in units of a0 (z: slab thickness)
SLABS = {
    "111": ("1 -1 0", "1 1 -2", "1 1 1", (3 * 2 ** 0.5, 2 * 6 ** 0.5, 4 * 3 ** 0.5)),
    "100": ("1 0 0", "0 1 0", "0 0 1", (4, 4, 6)),
    "110": ("0 0 1", "1 -1 0", "1 1 0", (4, 3 * 2 ** 0.5, 8 * 2 ** 0.5 / 2)),
}


# --------------------------------------------------------------------------- jobs
@dataclass
class Job:
    name: str
    template: str
    vars: dict
    gpu: bool = True
    deps: list = field(default_factory=list)


def _lmp_cmd(args, job: Job, gpu_id: int | None) -> list[str]:
    cmd = [args.lmp, "-in", str(TDIR / job.template), "-log", "log.lammps", "-screen", "screen.txt"]
    if gpu_id is not None and job.gpu:
        cmd += ["-k", "on", "g", "1", "-sf", "kk", "-pk", "kokkos", "newton", "off",
                "neigh", "full", "gpu/aware", "off"]
    for k, v in {"tdir": str(TDIR), **job.vars}.items():
        cmd += ["-var", k, str(v)]
    return cmd


def gpu_temps() -> dict[int, int]:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=index,temperature.gpu", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=20).stdout
        return {int(a): int(b) for a, b in (ln.split(",") for ln in out.strip().splitlines())}
    except Exception:
        return []


class Runner:
    """Small job queue: N slots per GPU (or CPU slots), thermal watchdog."""

    def __init__(self, args):
        self.args = args
        self.procs: dict[str, subprocess.Popen] = {}
        self.lock = threading.Lock()
        self.paused = False
        self.timings: dict[str, float] = {}

    def run_one(self, job: Job, gpu_id):
        wd = Path(self.args.rundir) / job.name
        wd.mkdir(parents=True, exist_ok=True)
        done = wd / "DONE"
        if done.exists():
            return
        env = dict(os.environ)
        if gpu_id is not None:
            env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
        env.setdefault("OMP_NUM_THREADS", "1")
        cmd = _lmp_cmd(self.args, job, gpu_id)
        if gpu_id is None and self.args.mpi > 1:
            cmd = ["mpirun", "-np", str(self.args.mpi)] + cmd
        t0 = time.time()
        p = subprocess.Popen(cmd, cwd=wd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        with self.lock:
            self.procs[job.name] = p
        rc = p.wait()
        with self.lock:
            self.procs.pop(job.name, None)
        dt = time.time() - t0
        if rc == 0:
            done.write_text(json.dumps({"wall_s": dt, "gpu": gpu_id, "cmd": cmd[1:]}))
        print(f"[{time.strftime('%H:%M:%S')}] {job.name} rc={rc} {dt:.0f}s gpu={gpu_id}", flush=True)

    def watchdog(self, stop: threading.Event):
        hi, lo = self.args.tmax, self.args.tmax - 8
        while not stop.wait(15):
            if not self.args.gpus:
                return
            mine = {int(g) for g in self.args.gpus.split(",")}
            temps = [t for g, t in gpu_temps().items() if g in mine]
            if not temps:
                continue
            with self.lock:
                if not self.paused and max(temps) >= hi:
                    for p in self.procs.values():
                        p.send_signal(signal.SIGSTOP)
                    self.paused = True
                    print(f"watchdog: GPU {temps} C >= {hi}: paused", flush=True)
                elif self.paused and max(temps) <= lo:
                    for p in self.procs.values():
                        p.send_signal(signal.SIGCONT)
                    self.paused = False
                    print(f"watchdog: GPU {temps} C: resumed", flush=True)

    def run(self, jobs: list[Job]):
        """GPU slots take jobs from the front of the list (callers put the
        biggest first), CPU slots from the back (smallest)."""
        if not jobs:
            return
        dq = collections.deque(jobs)
        slots = []
        if self.args.gpus:
            for g in self.args.gpus.split(","):
                slots += [int(g)] * self.args.jobs_per_gpu
        slots += [None] * self.args.cpu_slots
        stop = threading.Event()
        wd = threading.Thread(target=self.watchdog, args=(stop,), daemon=True)
        wd.start()

        def worker(gid):
            while True:
                with self.lock:
                    if not dq:
                        return
                    j = dq.popleft() if gid is not None else dq.pop()
                while self.paused:
                    time.sleep(5)
                self.run_one(j, gid)

        ths = [threading.Thread(target=worker, args=(g,)) for g in slots]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        stop.set()


# --------------------------------------------------------------------------- helpers
def _parse_result(path: Path, tag="RESULT") -> dict:
    out = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if line.startswith(tag + " "):
            toks = line.split()[1:]
            out.update({toks[i]: float(toks[i + 1]) for i in range(0, len(toks) - 1, 2)})
    return out


def _bulk(args, mat) -> dict:
    r = _parse_result(Path(args.rundir) / f"bulk_{mat}" / "log.lammps")
    if not r:
        raise RuntimeError(f"bulk_{mat} not finished")
    return r


def _pot(args, mat) -> str:
    return str(Path(args.potdir) / MATERIALS[mat]["pot"])


def _rot(seed):
    rng = np.random.default_rng(seed)
    ax = rng.normal(size=3)
    ax /= np.linalg.norm(ax)
    ang = rng.uniform(20, 70)
    return ax, ang


# --------------------------------------------------------------------------- stages
def stage_bulk(args, R: Runner):
    jobs = [Job(f"bulk_{m}", "bulk.in", {"pot": _pot(args, m), "mass": p["mass"], "a_guess": p["a_guess"]},
                gpu=False) for m, p in MATERIALS.items()]
    old, args.gpus = args.gpus, None
    old_slots, args.cpu_slots = args.cpu_slots, max(1, args.cpu_slots)
    R.run(jobs)
    jobs = []
    for m, p in MATERIALS.items():
        b = _bulk(args, m)
        for f, (ox, oy, oz, (lx, ly, lz)) in SLABS.items():
            jobs.append(Job(f"slab_{m}_{f}", "slab.in",
                            {"pot": _pot(args, m), "mass": p["mass"], "a0": b["a0"], "ecoh": b["ecoh"],
                             **{f"o{ax}{i + 1}": v for ax, vec in zip("xyz", (ox, oy, oz))
                                for i, v in enumerate(vec.split())},
                             "Lx": lx * b["a0"], "Ly": ly * b["a0"], "zslab": lz * b["a0"]}, gpu=False))
    R.run(jobs)
    args.gpus, args.cpu_slots = old, old_slots


def stage_cluster(args, R: Runner):
    jobs = []
    for m, p in MATERIALS.items():
        b = _bulk(args, m)
        for d in args.cluster_d:
            Rr = d * 5.0
            n_ann = int(args.t_ann_ps / p["dt"])
            jobs.append(Job(f"cluster_{m}_{d:g}", "cluster.in",
                            {"pot": _pot(args, m), "mass": p["mass"], "a0": b["a0"], "R": Rr, "L": Rr + 20,
                             "dt": p["dt"], "T_ann": args.t_ann[m], "seed": 1000 + int(d * 10),
                             "n_ann": n_ann, "n_cool": n_ann, "out": "cluster"}))
    jobs.sort(key=lambda j: -float(j.vars["R"]))
    R.run(jobs)


def stage_melt(args, R: Runner):
    jobs = []
    for m, p in MATERIALS.items():
        for d in args.melt_d:
            data = Path(args.rundir) / f"cluster_{m}_{d:g}" / "cluster.data"
            nrun = int(args.melt_ps / p["dt"])
            nave = int(2.0 / p["dt"] / 10)
            nevery = nave * 10  # ~2 ps bins
            jobs.append(Job(f"melt_{m}_{d:g}", "melt.in",
                            {"pot": _pot(args, m), "mass": p["mass"], "data": data, "dt": p["dt"],
                             "T0": 300, "T1": args.melt_T1, "seed": 7, "nrun": nrun,
                             "nevery": nevery, "nave": nave, "out": "melt"}))
    jobs.sort(key=lambda j: -float(j.name.split("_")[2]))
    R.run(jobs)


def stage_coalesce(args, R: Runner, annealed: bool = False):
    """Dimer coalescence grid. annealed=False: two as-cut spheres (coalesce.in);
    annealed=True: two copies of the annealed cluster from stage 'cluster'
    (coalesce_annealed.in, run-name prefix coalA_)."""
    jobs = []
    for m, p in MATERIALS.items():
        b = _bulk(args, m)
        for d in args.coal_d:
            for T in args.coal_T:
                for rep in range(args.reps if d <= args.reps_dmax else max(1, args.reps - 1)):
                    Rr = d * 5.0
                    gap0, gap1 = 8.0, 2.5  # A; EAM cutoff 5.55 A
                    xc = Rr + gap0 / 2
                    ax, ang = _rot(int(d * 100) + rep)
                    n_run = int(args.coal_ps / p["dt"])
                    extra = {}
                    if annealed:
                        extra = {"data": Path(args.rundir) / f"cluster_{m}_{d:g}" / "cluster.data"}
                    jobs.append(Job(f"{'coalA' if annealed else 'coal'}_{m}_{d:g}_{T}_r{rep}",
                                    "coalesce_annealed.in" if annealed else "coalesce.in",
                                    {"pot": _pot(args, m), "mass": p["mass"], "a0": b["a0"], "R": Rr,
                                     "xc": xc, "Lx": xc + Rr + 15, "L": Rr + 15,
                                     "ax": ax[0], "ay": ax[1], "az": ax[2], "ang": ang,
                                     "dt": p["dt"], "T": T, "seed": 4242 + rep,
                                     "n_eq": int(20 / p["dt"]), "shift": gap0 - gap1,
                                     "n_run": n_run, "nprint": max(1, int(2.0 / p["dt"])), "out": "coal",
                                     **extra}))
    # largest first so the long jobs start early
    jobs.sort(key=lambda j: -float(j.vars["R"]))
    R.run(jobs)


# --------------------------------------------------------------------------- analysis
def _wulff_free_gamma_fit(N, E_ex, v_at):
    """Fit E_ex(N) = a N^(2/3) + b N^(1/3) (surface + edge/corner) and return
    gamma_inf (J/m2) of the equivalent sphere and the Gibbs-Thomson gamma(d)."""
    N = np.asarray(N, float)
    E = np.asarray(E_ex, float)
    X = np.vstack([N ** (2 / 3), N ** (1 / 3)]).T
    (a, b), *_ = np.linalg.lstsq(X, E, rcond=None)
    # sphere: A = (36 pi)^(1/3) v^(2/3) N^(2/3)
    area_per_N23 = (36 * math.pi) ** (1 / 3) * v_at ** (2 / 3)  # A^2
    g_inf = a / area_per_N23 * EV_A2_TO_J_M2
    return a, b, g_inf


def analyze_bulk_slab(args) -> dict:
    out = {}
    for m in MATERIALS:
        b = _bulk(args, m)
        rec = {"ecoh_eV": b["ecoh"], "a0_A": b["a0"]}
        for f in SLABS:
            r = _parse_result(Path(args.rundir) / f"slab_{m}_{f}" / "log.lammps")
            rec[f"gamma_{f}_J_m2"] = r.get("gamma_Jm2")
        out[m] = rec
    return out


def analyze_clusters(args, bulk) -> list[dict]:
    rows = []
    for m in MATERIALS:
        a0, ecoh = bulk[m]["a0_A"], bulk[m]["ecoh_eV"]
        v_at = a0 ** 3 / 4
        for d in CLUSTER_D_NM + [x for x in args.cluster_d if x not in CLUSTER_D_NM]:
            wd = Path(args.rundir) / f"cluster_{m}_{d:g}"
            r = _parse_result(wd / "log.lammps")
            r0 = _parse_result(wd / "log.lammps", "RESULT0")
            if "pe" not in r:
                continue
            N = int(r["natoms"])
            d_eq = (6 * N * v_at / math.pi) ** (1 / 3)  # A
            # annealing can trap defects in big clusters: keep the lower of the two minima
            E_ex = min(r["pe"], r0["pe_cut"]) - N * ecoh
            E_ex_cut = r0["pe_cut"] - N * ecoh
            area = math.pi * d_eq ** 2
            rows.append({"material": m, "d_nominal_nm": d, "N": N, "d_eq_nm": round(d_eq / 10, 4),
                         "E_excess_eV": round(E_ex, 4), "E_excess_unannealed_eV": round(E_ex_cut, 4),
                         "gamma_eff_J_m2": round(E_ex / area * EV_A2_TO_J_M2, 4),
                         "wall_s": _wall(wd)})
    rows.sort(key=lambda r: (r["material"], r["N"]))
    # Gibbs-Thomson gamma: d(E_ex)/dN from the fit -> 2 gamma v/r
    for m in MATERIALS:
        sub = [r for r in rows if r["material"] == m]
        if len(sub) < 3:
            continue
        v_at = bulk[m]["a0_A"] ** 3 / 4
        a, b, g_inf = _wulff_free_gamma_fit([r["N"] for r in sub], [r["E_excess_eV"] for r in sub], v_at)
        for r in sub:
            N = r["N"]
            dmu = (2 / 3) * a * N ** (-1 / 3) + (1 / 3) * b * N ** (-2 / 3)  # eV/atom
            rad = r["d_eq_nm"] * 5.0  # A
            r["gamma_GT_J_m2"] = round(dmu * rad / (2 * v_at) * EV_A2_TO_J_M2, 4)
            r["fit_a_eV"] = round(a, 5)
            r["fit_b_eV"] = round(b, 5)
            r["gamma_inf_fit_J_m2"] = round(g_inf, 4)
    return rows


def _wall(wd: Path):
    f = wd / "DONE"
    w = json.loads(f.read_text()).get("wall_s") if f.exists() else None
    return round(w, 1) if w is not None else None


def _melt_T(path: Path):
    """Melting T from the PE(T) ramp: linear solid baseline (first 25 % of the
    ramp) and liquid baseline (last 15 %); Tm = T where the liquid fraction
    f = (PE - solid)/(liquid - solid) first exceeds 0.5 (20-ps running mean).
    Returns (Tm, latent heat per atom at Tm)."""
    if not path.exists():
        return None
    arr = np.loadtxt(path, comments="#")
    if arr.ndim != 2 or len(arr) < 40:
        return None
    k = 10
    T = np.convolve(arr[:, 1], np.ones(k) / k, mode="valid")
    pe = np.convolve(arr[:, 2], np.ones(k) / k, mode="valid")
    n = len(T)
    cs = np.polyfit(T[: n // 4], pe[: n // 4], 1)
    cl = np.polyfit(T[-int(n * 0.15):], pe[-int(n * 0.15):], 1)
    f = (pe - np.polyval(cs, T)) / (np.polyval(cl, T) - np.polyval(cs, T))
    idx = np.nonzero(f > 0.5)[0]
    if not len(idx):
        return None
    Tm = float(T[idx[0]])
    return Tm, float(np.polyval(cl, Tm) - np.polyval(cs, Tm))


def analyze_melt(args, clusters) -> list[dict]:
    rows = []
    Nmap = {(r["material"], r["d_nominal_nm"]): r for r in clusters}
    for m in MATERIALS:
        for d in sorted(set(MELT_D_NM + list(args.melt_d))):
            wd = Path(args.rundir) / f"melt_{m}_{d:g}"
            res = _melt_T(wd / "melt.melt.txt")
            if res is None or not (wd / "DONE").exists():
                continue
            c = Nmap.get((m, d), {})
            rows.append({"material": m, "d_nominal_nm": d, "N": c.get("N"), "d_eq_nm": c.get("d_eq_nm"),
                         "Tm_K": round(res[0], 1), "latent_eV_atom": round(res[1], 4),
                         "ramp_K_per_ps": round((args.melt_T1 - 300) / args.melt_ps, 3), "wall_s": _wall(wd)})
    return rows


def _shape_series(path: Path):
    arr = np.loadtxt(path, comments="#")
    t, pe = arr[:, 0], arr[:, 2]
    asp = []
    for row in arr:
        g = np.array([[row[3], row[6], row[7]], [row[6], row[4], row[8]], [row[7], row[8], row[5]]])
        ev = np.sort(np.linalg.eigvalsh(g))
        asp.append(math.sqrt(ev[2] / ev[0]))
    return t, pe, np.array(asp)


def analyze_coalesce(args) -> tuple[list[dict], dict]:
    """Coalescence progress from the principal radii of gyration.

    For two touching equal spheres sqrt(l_max/l_min) = sqrt(6) = 2.45; a compact
    particle gives ~1.0-1.1. The normalised elongation
        xi(t) = (s(t) - s_eq) / (sqrt(6) - s_eq),  s = sqrt(l_max/l_min), s_eq = 1.05
    goes 1 -> 0. tau_50 / tau_80: first time the 20-ps running mean of xi drops
    below 0.5 / 0.2 (None = not reached in the run).
    """
    rows, series = [], {}
    s_eq, s0 = 1.05, math.sqrt(6)
    for wd in sorted(Path(args.rundir).glob("coal*_*")):
        f = wd / "coal.coal.txt"
        if not f.exists() or _wall(wd) is None:  # unfinished, or a placeholder for a job run elsewhere
            continue
        kind, m, d, T, rep = wd.name.split("_")
        t, pe, s = _shape_series(f)
        xi = (s - s_eq) / (s0 - s_eq)
        w = max(1, int(round(20.0 / max(t[1] - t[0], 1e-9))))
        xs = np.convolve(xi, np.ones(w) / w, mode="valid")
        ts = t[w - 1:]

        def first_below(th):
            idx = np.nonzero(xs < th)[0]
            return float(ts[idx[0]]) if len(idx) else None

        n = len(t)
        tail = slice(int(n * 0.9), n)
        rows.append({"material": m, "d_nm": float(d), "T_K": int(T), "rep": rep,
                     "start": "annealed" if kind == "coalA" else "as-cut",
                     "t_run_ps": round(float(t[-1]), 1),
                     "xi_after_10ps": round(float(np.mean(xi[(t > 5) & (t < 15)])), 3),
                     "xi_final": round(float(np.mean(xi[tail])), 3),
                     "tau50_ps": first_below(0.5), "tau80_ps": first_below(0.2),
                     "dPE_eV_atom": round(float(np.mean(pe[tail]) - pe[0]), 5),
                     "wall_s": _wall(wd)})
        series[wd.name] = {"t_ps": [round(x, 1) for x in t[::5].tolist()],
                           "xi": [round(x, 3) for x in xi[::5].tolist()]}
    rows.sort(key=lambda r: (r["start"], r["material"], r["d_nm"], r["T_K"], r["rep"]))
    return rows, series


def _write_csv(path: Path, rows: list[dict]):
    if not rows:
        return
    keys = list(rows[0].keys())
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def stage_analyze(args):
    DATA.mkdir(exist_ok=True)
    bulk = analyze_bulk_slab(args)
    (DATA / "md_bulk_slab.json").write_text(json.dumps(bulk, indent=1))
    cl = analyze_clusters(args, bulk)
    _write_csv(DATA / "md_clusters.csv", cl)
    me = analyze_melt(args, cl)
    _write_csv(DATA / "md_melting.csv", me)
    co, series = analyze_coalesce(args)
    _write_csv(DATA / "md_coalescence.csv", co)
    (DATA / "md_coalescence_series.json").write_text(json.dumps(series, separators=(",", ":")))
    print(json.dumps(bulk, indent=1))
    for rows in (cl, me, co):
        for r in rows:
            print(r)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lmp", default="lmp", help="LAMMPS executable")
    ap.add_argument("--potdir", default=os.environ.get("LAMMPS_POTENTIALS", "."))
    ap.add_argument("--rundir", default="build/atomistic_runs")
    ap.add_argument("--stage", default="all",
                    choices=["bulk", "cluster", "melt", "coalesce", "coalesce_annealed", "analyze", "all"])
    ap.add_argument("--gpus", default=None, help="comma list, e.g. 0,1 (KOKKOS-CUDA); omit for CPU")
    ap.add_argument("--jobs-per-gpu", type=int, default=2)
    ap.add_argument("--cpu-slots", type=int, default=0, help="extra single-core CPU job slots")
    ap.add_argument("--mpi", type=int, default=1, help="MPI ranks per CPU job")
    ap.add_argument("--tmax", type=int, default=83)
    ap.add_argument("--cluster-d", type=float, nargs="*", default=CLUSTER_D_NM)
    ap.add_argument("--melt-d", type=float, nargs="*", default=MELT_D_NM)
    ap.add_argument("--coal-d", type=float, nargs="*", default=COAL_D_NM)
    ap.add_argument("--coal-T", type=int, nargs="*", default=COAL_T_K)
    ap.add_argument("--coal-ps", type=float, default=2500.0)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--reps-dmax", type=float, default=5.0, help="above this d use reps-1 replicas")
    ap.add_argument("--t-ann-ps", type=float, default=200.0)
    ap.add_argument("--melt-ps", type=float, default=1000.0)
    ap.add_argument("--melt-T1", type=float, default=1400.0)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.t_ann = {"Au": 500, "Ag": 500}
    args.rundir = str(Path(args.rundir).resolve())
    R = Runner(args)
    st = args.stage
    if st in ("bulk", "all"):
        stage_bulk(args, R)
    if st in ("cluster", "all"):
        stage_cluster(args, R)
    if st in ("melt", "all"):
        stage_melt(args, R)
    if st in ("coalesce", "all"):
        stage_coalesce(args, R)
    if st == "coalesce_annealed":
        stage_coalesce(args, R, annealed=True)
    if st in ("analyze", "all"):
        stage_analyze(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
