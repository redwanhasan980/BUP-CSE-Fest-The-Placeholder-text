from __future__ import annotations

from dataclasses import dataclass

from app.directives import EffectiveParams
from app.optimizer import Solution
from app.schemas import HourlyPlanEntry

ACTION_TOL = 1e-6


def _r4(x: float) -> float:
    v = round(float(x), 4)
    if v == 0.0:
        return 0.0  # avoid -0.0
    if -1e-3 < v < 0.0:
        return 0.0  # clamp tiny negative noise
    return v


@dataclass
class BuiltPlan:
    hourly_plan: list[HourlyPlanEntry]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float


def build_plan(p: EffectiveParams, sol: Solution) -> BuiltPlan:
    """Convert LP solution to the rounded hourly_plan and recompute all
    totals FROM the rounded plan (FR-OUT-02/03)."""
    entries: list[HourlyPlanEntry] = []
    prev_energy = p.initial

    for h in range(24):
        grid = _r4(sol.g[h])
        solar_used = _r4(sol.s[h])
        net = round(sol.c[h] - sol.d[h], 4)

        if net > ACTION_TOL:
            action, battery_kwh, signed = "charge", _r4(net), _r4(net)
        elif net < -ACTION_TOL:
            action, battery_kwh, signed = "discharge", _r4(-net), _r4(net)
        else:
            action, battery_kwh, signed = "idle", 0.0, 0.0

        energy_after = _r4(prev_energy + signed)
        prev_energy = energy_after

        entries.append(HourlyPlanEntry(
            hour=h, grid_kwh=grid, solar_used_kwh=solar_used,
            battery_action=action, battery_kwh=battery_kwh,
            battery_energy_after_kwh=energy_after,
        ))

    total_grid = _r4(sum(e.grid_kwh for e in entries))
    total_cost = _r4(sum(e.grid_kwh * p.tariff[e.hour] for e in entries))
    peak = _r4(max(e.grid_kwh for e in entries))

    return BuiltPlan(entries, total_grid, total_cost, peak)
