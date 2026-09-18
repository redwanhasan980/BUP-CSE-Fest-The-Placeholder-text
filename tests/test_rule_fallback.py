"""Degraded-mode parser on phrasings it is designed to handle."""
from __future__ import annotations

import pytest

from app.llm.rule_fallback import parse_note

CAP = 200.0


def p(note):
    return parse_note(note, 0, CAP)


# --- no_op distractors ---
@pytest.mark.parametrize("note", [
    "The cafeteria menu changes tomorrow.",
    "The sports office moved next month's registration deadline.",
    "The debate club meeting was rescheduled.",
    "Last week's power outage has been resolved.",
])
def test_no_op(note):
    assert p(note).directive_type == "no_op"


def test_cancellation_is_no_op():
    assert p("The 2-4 PM battery maintenance has been cancelled.").directive_type == "no_op"


# --- typed directives ---
def test_no_charge():
    d = p("Do not charge the battery between 2 PM and 4 PM.")
    assert d.directive_type == "no_charge_window" and d.hours == [14, 15]


def test_no_charge_isolated():
    d = p("The battery charger will be isolated from 2 AM until 5 AM for maintenance.")
    assert d.directive_type == "no_charge_window" and d.hours == [2, 3, 4]


def test_no_discharge():
    d = p("For protection testing, the battery must not discharge from 6 PM until 8 PM.")
    assert d.directive_type == "no_discharge_window" and d.hours == [18, 19]


def test_reserve_kwh():
    d = p("Keep at least 90 kWh in the battery from 6 PM until 10 PM.")
    assert d.directive_type == "minimum_battery_reserve"
    assert d.hours == [18, 19, 20, 21] and d.minimum_energy_kwh == 90


def test_reserve_percent():
    d = p("Keep at least 50% of the battery capacity from 6 PM until 9 PM.")
    assert d.directive_type == "minimum_battery_reserve"
    assert d.hours == [18, 19, 20] and d.minimum_energy_kwh == 100  # 50% of 200


def test_max_grid():
    d = p("From 6 PM until 9 PM, grid import must not exceed 155 kWh in any hour.")
    assert d.directive_type == "max_grid_window"
    assert d.hours == [18, 19, 20] and d.max_grid_kwh == 155


def test_solar_drop_to_percent():
    d = p("Solar output will drop to about 20% from 1 PM to 3 PM.")
    assert d.directive_type == "solar_reduction"
    assert d.hours == [13, 14] and abs(d.factor - 0.2) < 1e-9


def test_solar_reduction_by_percent():
    d = p("Expect an 80% reduction in rooftop solar during the 11 AM to 2 PM window.")
    assert d.directive_type == "solar_reduction"
    assert d.hours == [11, 12, 13] and abs(d.factor - 0.2) < 1e-9


def test_solar_daylight_inference():
    d = p("Panel washing from one until three will leave roughly 25% of solar output.")
    assert d.directive_type == "solar_reduction"
    assert d.hours == [13, 14] and abs(d.factor - 0.25) < 1e-9
