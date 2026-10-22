"""The mixing gate: does the reactor scale need CFD, or is a lumped (well-mixed)
reactor enough?  (find-simulations protocol, step "mixing")

    Da = t_mix / t_chem

t_chem is the fastest chemical step the vessel has to keep up with (reduction,
nucleation burst, precipitation), named by the agent with its source. t_mix is
the vessel's 95 % mixing time: a simulated or measured value when the study has
one, else Grenville's correlation for a stirred vessel,

    theta_95 = 5.2 / (N_p^(1/3) N) * (T / D)^2      (N in rev/s, T vessel, D impeller)

which is conservative for a magnetic stir bar. Da below GATE keeps the reactor
lumped; above it, the reaction runs inside the injection plume, so the flow
sets where and at what local excess it happens and the reactor scale needs CFD
(advection-diffusion-reaction on the vessel). Between GATE and 1 the verdict is
marginal: a CFD-lite check of the vessel decides.

    gate(m) -> the agent's numbers plus t_mix, Da, verdict and the reason
"""
from __future__ import annotations

GATE = 0.1
POWER_NUMBER = 0.6          # stir bar (assumed when the agent gives none)


def grenville(rpm: float, impeller_mm: float, vessel_mm: float, power_number: float = POWER_NUMBER) -> float:
    """Grenville's 95 % blend time (s) for a stirred vessel."""
    n = rpm / 60.0
    return 5.2 / (power_number ** (1 / 3) * n) * (vessel_mm / impeller_mm) ** 2


def verdict(da: float) -> str:
    return "lumped" if da < GATE else "marginal" if da < 1.0 else "cfd"


REASON = {
    "lumped": "the liquid is uniform before the reaction starts: a lumped, well-mixed reactor is exact",
    "marginal": "mixing and reaction overlap: a CFD-lite check of the vessel decides",
    "cfd": "the reaction runs inside the injection plume before the vessel mixes: the flow sets where "
           "and at what local excess it happens, so the reactor scale needs CFD",
}


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def gate(m: dict) -> dict | None:
    """The agent's mixing numbers -> the gate (None when t_chem or every t_mix is missing)."""
    if not isinstance(m, dict):
        return None
    t_chem = _num(m.get("t_chem_s"))
    rpm, imp, ves = _num(m.get("rpm")), _num(m.get("impeller_mm")), _num(m.get("vessel_mm"))
    corr = grenville(rpm, imp, ves, _num(m.get("power_number")) or POWER_NUMBER) if rpm and imp and ves else None
    given = _num(m.get("t_mix_s"))
    t_mix = given or corr
    if not t_chem or not t_mix:
        return None
    da = t_mix / t_chem
    v = verdict(da)
    alts = []
    for a in m.get("alternatives") or []:
        tc = _num((a or {}).get("t_chem_s"))
        if tc and str(a.get("process", "")).strip():
            alts.append({"process": str(a["process"])[:80], "t_chem_s": tc, "Da": t_mix / tc,
                         "verdict": verdict(t_mix / tc)})
    out = {k: m[k] for k in ("process", "t_chem_source", "vessel", "t_mix_source", "note") if m.get(k)}
    out.update({"t_chem_s": t_chem, "t_mix_s": t_mix, "t_mix_from": "given" if given else "grenville",
                "grenville_s": corr, "rpm": rpm, "impeller_mm": imp, "vessel_mm": ves,
                "power_number": _num(m.get("power_number")) or POWER_NUMBER,
                "Da": da, "Da_grenville": corr / t_chem if corr else None, "gate": GATE,
                "verdict": v, "reason": REASON[v], "alternatives": alts})
    return out
