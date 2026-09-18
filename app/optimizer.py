from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog

from app.directives import EffectiveParams

EPS = 1e-6  # throughput penalty to avoid simultaneous charge/discharge

# Variable layout (24 each): g=grid, s=solar_used, c=charge, d=discharge, E=energy_after
_N = 24
_G, _S, _C, _D, _E = 0, _N, 2 * _N, 3 * _N, 4 * _N
_NVARS = 5 * _N


@dataclass
class Solution:
    feasible: bool
    g: list[float]
    s: list[float]
    c: list[float]
    d: list[float]
    E: list[float]


def _solve(p: EffectiveParams) -> Solution:
    cost = np.zeros(_NVARS)
    for h in range(_N):
        cost[_G + h] = p.tariff[h]
        cost[_C + h] = EPS
        cost[_D + h] = EPS

    # Equality constraints
    rows = []
    b = []

    # Energy balance: g + s + d - c = demand
    for h in range(_N):
        row = np.zeros(_NVARS)
        row[_G + h] = 1.0
        row[_S + h] = 1.0
        row[_D + h] = 1.0
        row[_C + h] = -1.0
        rows.append(row)
        b.append(p.demand[h])

    # State transition: E[h] - E[h-1] - c[h] + d[h] = 0 ; h=0 uses initial
    for h in range(_N):
        row = np.zeros(_NVARS)
        row[_E + h] = 1.0
        row[_C + h] = -1.0
        row[_D + h] = 1.0
        if h == 0:
            rows.append(row)
            b.append(p.initial)
        else:
            row[_E + (h - 1)] = -1.0
            rows.append(row)
            b.append(0.0)

    # End-of-day neutrality: E[23] = initial
    row = np.zeros(_NVARS)
    row[_E + (_N - 1)] = 1.0
    rows.append(row)
    b.append(p.initial)

    A_eq = np.array(rows)
    b_eq = np.array(b)

    bounds = [(None, None)] * _NVARS
    for h in range(_N):
        bounds[_G + h] = (0.0, p.gmax[h])
        bounds[_S + h] = (0.0, max(0.0, p.eff_solar[h]))
        bounds[_C + h] = (0.0, max(0.0, p.cmax[h]))
        bounds[_D + h] = (0.0, max(0.0, p.dmax[h]))
        bounds[_E + h] = (p.emin[h], p.capacity)

    res = linprog(cost, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if not res.success:
        return Solution(False, [], [], [], [], [])

    x = res.x
    return Solution(
        True,
        list(x[_G:_G + _N]),
        list(x[_S:_S + _N]),
        list(x[_C:_C + _N]),
        list(x[_D:_D + _N]),
        list(x[_E:_E + _N]),
    )


def solve(p: EffectiveParams) -> Solution:
    return _solve(p)
