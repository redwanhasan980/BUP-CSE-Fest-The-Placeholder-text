from __future__ import annotations

from app.directives import Directive
from app.plan import BuiltPlan

_LABELS = {
    "solar_reduction": "reduced solar",
    "minimum_battery_reserve": "battery reserve",
    "no_charge_window": "no-charge window",
    "no_discharge_window": "no-discharge window",
    "max_grid_window": "grid cap",
}


def build_summary(directives: list[Directive], plan: BuiltPlan) -> str:
    applied = [d for d in directives if d.applies]
    noop = len(directives) - len(applied)

    parts: list[str] = []
    if applied:
        labels = ", ".join(_LABELS.get(d.directive_type, d.directive_type) for d in applied)
        parts.append(f"Applied {len(applied)} directive(s) ({labels}).")
    else:
        parts.append("No operator directives affected the schedule.")
    if noop:
        parts.append(f"{noop} note(s) ignored as no_op.")
    parts.append(
        f"Battery shifts energy toward higher-tariff hours and returns to its "
        f"initial level. Total grid {plan.total_grid_kwh} kWh, "
        f"cost {plan.total_cost_bdt} BDT, peak {plan.peak_grid_kwh} kWh."
    )
    return " ".join(parts)
