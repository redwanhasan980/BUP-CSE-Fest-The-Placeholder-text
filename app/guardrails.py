from __future__ import annotations

import math

from app.directives import DIRECTIVE_TYPES, Directive


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def validate(directives: list[Directive], n_notes: int, capacity: float) -> list[str]:
    """Deterministic guardrails on normalized directives (SRS §8.1).

    Returns a list of violation reasons; empty means the interpretation is
    safe to send to the optimizer.
    """
    reasons: list[str] = []

    # G-03: exactly one entry per note, indices 0..N-1 unique
    indices = [d.note_index for d in directives]
    if len(directives) != n_notes or sorted(indices) != list(range(n_notes)):
        reasons.append(f"G-03 note mapping must be exactly indices 0..{n_notes - 1}")

    for d in directives:
        tag = f"note {d.note_index}"

        # G-02: allowed types
        if d.directive_type not in DIRECTIVE_TYPES:
            reasons.append(f"G-02 {tag}: unsupported directive_type '{d.directive_type}'")
            continue

        if d.directive_type == "no_op":
            continue

        # G-04: hours are unique integers 0..23 ascending
        h = d.hours
        if (not h or any(not isinstance(x, int) or x < 0 or x > 23 for x in h)
                or h != sorted(set(h))):
            reasons.append(f"G-05/G-04 {tag}: hours must be non-empty unique ints 0..23 ascending")

        # G-06: solar factor
        if d.directive_type == "solar_reduction":
            if not _finite(d.factor) or not (0.0 <= d.factor <= 1.0):
                reasons.append(f"G-06 {tag}: factor must be finite in [0,1] (got {d.factor})")

        # G-07: reserve
        if d.directive_type == "minimum_battery_reserve":
            if not _finite(d.minimum_energy_kwh) or not (0.0 <= d.minimum_energy_kwh <= capacity):
                reasons.append(f"G-07 {tag}: reserve must be finite in [0,capacity] (got {d.minimum_energy_kwh})")

        # G-08: grid cap
        if d.directive_type == "max_grid_window":
            if not _finite(d.max_grid_kwh) or d.max_grid_kwh < 0:
                reasons.append(f"G-08 {tag}: max_grid_kwh must be finite and >= 0 (got {d.max_grid_kwh})")

    return reasons
