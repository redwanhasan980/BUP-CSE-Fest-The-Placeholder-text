from __future__ import annotations

import math

from app.directives import EffectiveParams
from app.plan import BuiltPlan
from app.schemas import HourlyPlanEntry

TOL = 0.01


def verify(p: EffectiveParams, plan: BuiltPlan) -> list[str]:
    """Replay the plan against every rule (SRS §8.2). Returns a list of
    violation reasons; empty list means the plan is valid."""
    reasons: list[str] = []
    entries = plan.hourly_plan

    # V-01: 24 entries, hours 0..23 ascending
    if [e.hour for e in entries] != list(range(24)):
        reasons.append("V-01 hours are not exactly 0..23 ascending")
        return reasons  # everything else assumes 24 ordered entries

    prev_energy = p.initial
    for h, e in enumerate(entries):
        charge = e.battery_kwh if e.battery_action == "charge" else 0.0
        discharge = e.battery_kwh if e.battery_action == "discharge" else 0.0

        # V-02: finite and non-negative
        for name, val in (("grid", e.grid_kwh), ("solar_used", e.solar_used_kwh),
                          ("battery_kwh", e.battery_kwh),
                          ("battery_energy_after", e.battery_energy_after_kwh)):
            if not math.isfinite(val) or val < -TOL:
                reasons.append(f"V-02 hour {h}: {name} not finite/non-negative")

        # V-03: action enum + idle => 0
        if e.battery_action not in ("charge", "discharge", "idle"):
            reasons.append(f"V-03 hour {h}: invalid action {e.battery_action}")
        if e.battery_action == "idle" and abs(e.battery_kwh) > TOL:
            reasons.append(f"V-03 hour {h}: idle with non-zero battery_kwh")

        # V-04: energy balance
        lhs = e.grid_kwh + e.solar_used_kwh + discharge
        rhs = p.demand[h] + charge
        if abs(lhs - rhs) > TOL:
            reasons.append(f"V-04 hour {h}: energy balance off ({lhs} vs {rhs})")

        # V-05: solar usage <= effective solar
        if e.solar_used_kwh > p.eff_solar[h] + TOL:
            reasons.append(f"V-05 hour {h}: solar_used {e.solar_used_kwh} > effective {p.eff_solar[h]}")

        # V-06: transitions
        signed = charge - discharge
        if abs(e.battery_energy_after_kwh - (prev_energy + signed)) > TOL:
            reasons.append(f"V-06 hour {h}: bad transition")

        # V-07: battery bounds with directive-raised minimum
        if e.battery_energy_after_kwh < p.emin[h] - TOL:
            reasons.append(f"V-07 hour {h}: energy {e.battery_energy_after_kwh} < min {p.emin[h]}")
        if e.battery_energy_after_kwh > p.capacity + TOL:
            reasons.append(f"V-07 hour {h}: energy {e.battery_energy_after_kwh} > capacity {p.capacity}")

        # V-08: rate limits
        if charge > p.cmax[h] + TOL:
            reasons.append(f"V-08 hour {h}: charge {charge} > max {p.cmax[h]}")
        if discharge > p.dmax[h] + TOL:
            reasons.append(f"V-08 hour {h}: discharge {discharge} > max {p.dmax[h]}")

        # V-09: directive windows
        if p.no_charge[h] and charge > TOL:
            reasons.append(f"V-09 hour {h}: charging in no_charge_window")
        if p.no_discharge[h] and discharge > TOL:
            reasons.append(f"V-09 hour {h}: discharging in no_discharge_window")

        # V-10: grid cap
        if p.gmax[h] is not None and e.grid_kwh > p.gmax[h] + TOL:
            reasons.append(f"V-10 hour {h}: grid {e.grid_kwh} > cap {p.gmax[h]}")

        prev_energy = e.battery_energy_after_kwh

    # V-11: end-of-day neutrality
    if abs(entries[-1].battery_energy_after_kwh - p.initial) > TOL:
        reasons.append("V-11 end-of-day battery energy != initial")

    # V-12: totals recomputed from plan
    total_grid = sum(e.grid_kwh for e in entries)
    total_cost = sum(e.grid_kwh * p.tariff[e.hour] for e in entries)
    peak = max(e.grid_kwh for e in entries)
    if abs(total_grid - plan.total_grid_kwh) > TOL:
        reasons.append("V-12 total_grid_kwh mismatch")
    if abs(total_cost - plan.total_cost_bdt) > TOL:
        reasons.append("V-12 total_cost_bdt mismatch")
    if abs(peak - plan.peak_grid_kwh) > TOL:
        reasons.append("V-12 peak_grid_kwh mismatch")

    return reasons
