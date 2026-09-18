from __future__ import annotations

from app.directives import Directive
from app.guardrails import validate


def ok(directives, n, cap=200):
    return validate(directives, n, cap) == []


def has(directives, n, code, cap=200):
    return any(code in r for r in validate(directives, n, cap))


def test_valid_passes():
    ds = [Directive(0, "solar_reduction", hours=[12, 13], factor=0.25)]
    assert ok(ds, 1)


def test_valid_no_op_passes():
    assert ok([Directive(0, "no_op")], 1)


def test_unsupported_type():
    assert has([Directive(0, "turn_off_everything", hours=[1])], 1, "G-02")


def test_wrong_entry_count():
    assert has([Directive(0, "no_op")], 2, "G-03")


def test_duplicate_index():
    ds = [Directive(0, "no_op"), Directive(0, "no_op")]
    assert has(ds, 2, "G-03")


def test_missing_index():
    ds = [Directive(0, "no_op"), Directive(2, "no_op")]
    assert has(ds, 2, "G-03")


def test_non_noop_empty_hours():
    assert has([Directive(0, "no_charge_window", hours=[])], 1, "G-05")


def test_hours_out_of_range():
    assert has([Directive(0, "no_charge_window", hours=[24])], 1, "G-05")


def test_hours_not_sorted_or_dup():
    assert has([Directive(0, "no_charge_window", hours=[3, 3, 1])], 1, "G-05")


def test_factor_above_one_percentage_error():
    # LLM returned 20 instead of 0.2 -> must be flagged, never silently used
    assert has([Directive(0, "solar_reduction", hours=[12], factor=20)], 1, "G-06")


def test_factor_negative():
    assert has([Directive(0, "solar_reduction", hours=[12], factor=-0.1)], 1, "G-06")


def test_factor_zero_and_one_ok():
    assert ok([Directive(0, "solar_reduction", hours=[12], factor=0.0)], 1)
    assert ok([Directive(0, "solar_reduction", hours=[12], factor=1.0)], 1)


def test_reserve_exceeds_capacity():
    assert has([Directive(0, "minimum_battery_reserve", hours=[18], minimum_energy_kwh=500)], 1, "G-07")


def test_reserve_negative():
    assert has([Directive(0, "minimum_battery_reserve", hours=[18], minimum_energy_kwh=-1)], 1, "G-07")


def test_grid_cap_negative():
    assert has([Directive(0, "max_grid_window", hours=[19], max_grid_kwh=-5)], 1, "G-08")


def test_grid_cap_zero_ok():
    assert ok([Directive(0, "max_grid_window", hours=[19], max_grid_kwh=0)], 1)
