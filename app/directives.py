from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.schemas import Battery, HourEntry

DIRECTIVE_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}


@dataclass
class Directive:
    """Normalized, validated interpretation of a single operator note."""

    note_index: int
    directive_type: str
    hours: list[int] = field(default_factory=list)
    factor: Optional[float] = None
    minimum_energy_kwh: Optional[float] = None
    max_grid_kwh: Optional[float] = None
    explanation: str = ""

    @property
    def applies(self) -> bool:
        return self.directive_type != "no_op"

    def structured_adjustment(self) -> Optional[dict]:
        t = self.directive_type
        if t == "no_op":
            return None
        if t == "solar_reduction":
            return {"hours": self.hours, "factor": self.factor}
        if t == "minimum_battery_reserve":
            return {"hours": self.hours, "minimum_energy_kwh": self.minimum_energy_kwh}
        if t == "max_grid_window":
            return {"hours": self.hours, "max_grid_kwh": self.max_grid_kwh}
        # no_charge_window, no_discharge_window
        return {"hours": self.hours}


@dataclass
class EffectiveParams:
    demand: list[float]
    tariff: list[float]
    eff_solar: list[float]
    emin: list[float]
    cmax: list[float]
    dmax: list[float]
    gmax: list[Optional[float]]  # None = +inf
    no_charge: list[bool]
    no_discharge: list[bool]
    capacity: float
    initial: float


def compute_effective_params(
    hours: list[HourEntry], battery: Battery, directives: list[Directive]
) -> EffectiveParams:
    """Apply applicable directives to base parameters (SRS §7.3, A-03).

    Overlaps of the same type: solar factors multiply, reserves take the max,
    grid caps take the min, no-charge/no-discharge union.
    """
    hs = sorted(hours, key=lambda h: h.hour)
    demand = [h.demand_kwh for h in hs]
    tariff = [h.tariff_bdt_per_kwh for h in hs]
    eff_solar = [h.solar_kwh for h in hs]
    emin = [battery.minimum_energy_kwh] * 24
    cmax = [battery.max_charge_kwh_per_hour] * 24
    dmax = [battery.max_discharge_kwh_per_hour] * 24
    gmax: list[Optional[float]] = [None] * 24
    no_charge = [False] * 24
    no_discharge = [False] * 24

    for d in directives:
        if not d.applies:
            continue
        for h in d.hours:
            if d.directive_type == "solar_reduction":
                eff_solar[h] = eff_solar[h] * float(d.factor)
            elif d.directive_type == "minimum_battery_reserve":
                emin[h] = max(emin[h], float(d.minimum_energy_kwh))
            elif d.directive_type == "no_charge_window":
                cmax[h] = 0.0
                no_charge[h] = True
            elif d.directive_type == "no_discharge_window":
                dmax[h] = 0.0
                no_discharge[h] = True
            elif d.directive_type == "max_grid_window":
                cap = float(d.max_grid_kwh)
                gmax[h] = cap if gmax[h] is None else min(gmax[h], cap)

    return EffectiveParams(
        demand=demand, tariff=tariff, eff_solar=eff_solar, emin=emin,
        cmax=cmax, dmax=dmax, gmax=gmax, no_charge=no_charge,
        no_discharge=no_discharge, capacity=battery.capacity_kwh,
        initial=battery.initial_energy_kwh,
    )
