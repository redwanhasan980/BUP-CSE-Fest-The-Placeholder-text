from __future__ import annotations

from app.directives import Directive
from app.schemas import IRInterpretation, IRResponse, IRWindow


def expand_window(start: int, end: int) -> list[int]:
    """Expand an IR window [start, end) into integer hours.

    end == 24 means midnight at day end. end < start wraps over midnight
    (e.g. 22->2 gives [22, 23, 0, 1]). Hours outside 0..23 are dropped.
    """
    if not isinstance(start, int) or not isinstance(end, int):
        return []
    if end == start:
        return []
    if end < start:
        rng = list(range(start, 24)) + list(range(0, end))
    else:
        rng = list(range(start, end))
    return sorted({h for h in rng if 0 <= h <= 23})


def _hours_from_windows(windows: list[IRWindow]) -> list[int]:
    hours: set[int] = set()
    for w in windows:
        hours.update(expand_window(w.start_hour, w.end_hour))
    return sorted(hours)


def normalize_one(ir: IRInterpretation, capacity: float) -> Directive:
    t = ir.directive_type
    if t == "no_op":
        return Directive(note_index=ir.note_index, directive_type="no_op",
                         explanation=ir.explanation)

    hours = _hours_from_windows(ir.windows)

    if t == "minimum_battery_reserve":
        value = ir.minimum_energy_kwh
        if value is None and ir.reserve_percent_of_capacity is not None:
            value = ir.reserve_percent_of_capacity / 100.0 * capacity
        return Directive(note_index=ir.note_index, directive_type=t, hours=hours,
                         minimum_energy_kwh=value, explanation=ir.explanation)

    if t == "solar_reduction":
        return Directive(note_index=ir.note_index, directive_type=t, hours=hours,
                         factor=ir.factor, explanation=ir.explanation)

    if t == "max_grid_window":
        return Directive(note_index=ir.note_index, directive_type=t, hours=hours,
                         max_grid_kwh=ir.max_grid_kwh, explanation=ir.explanation)

    # no_charge_window / no_discharge_window (or unknown -> passed through for guardrails)
    return Directive(note_index=ir.note_index, directive_type=t, hours=hours,
                     explanation=ir.explanation)


def normalize_ir(ir: IRResponse, capacity: float) -> list[Directive]:
    directives = [normalize_one(item, capacity) for item in ir.interpretations]
    directives.sort(key=lambda d: d.note_index)
    return directives
