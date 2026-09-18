from __future__ import annotations

import pytest

from app.normalizer import expand_window, normalize_one
from app.schemas import IRInterpretation, IRWindow


@pytest.mark.parametrize("start,end,expected", [
    (13, 15, [13, 14]),          # 1 PM to 3 PM
    (12, 14, [12, 13]),          # noon until 2 PM
    (22, 24, [22, 23]),          # 10 PM until midnight
    (19, 20, [19]),              # single hour 7 PM
    (18, 21, [18, 19, 20]),      # 3 hours from 6 PM
    (21, 24, [21, 22, 23]),      # after 9 PM
    (0, 6, [0, 1, 2, 3, 4, 5]),  # before 6 AM
    (0, 24, list(range(24))),    # all day
    (22, 2, [0, 1, 22, 23]),     # crosses midnight -> wrap + sort
    (5, 5, []),                  # empty
])
def test_expand_window(start, end, expected):
    assert expand_window(start, end) == expected


def _ir(dtype, windows=None, **kw):
    ws = [IRWindow(start_hour=a, end_hour=b) for a, b in (windows or [])]
    return IRInterpretation(note_index=0, directive_type=dtype, windows=ws, **kw)


def test_multiple_windows_union_sorted():
    d = normalize_one(_ir("no_charge_window", [(1, 2), (4, 5)]), capacity=200)
    assert d.hours == [1, 4]


def test_solar_factor_passthrough():
    d = normalize_one(_ir("solar_reduction", [(12, 14)], factor=0.2), capacity=200)
    assert d.hours == [12, 13] and d.factor == 0.2


def test_reserve_percent_converted():
    d = normalize_one(_ir("minimum_battery_reserve", [(18, 21)],
                          reserve_percent_of_capacity=50), capacity=200)
    assert d.minimum_energy_kwh == 100
    assert d.hours == [18, 19, 20]


def test_reserve_absolute_passthrough():
    d = normalize_one(_ir("minimum_battery_reserve", [(18, 22)],
                          minimum_energy_kwh=90), capacity=200)
    assert d.minimum_energy_kwh == 90


def test_max_grid_passthrough():
    d = normalize_one(_ir("max_grid_window", [(18, 21)], max_grid_kwh=155), capacity=200)
    assert d.max_grid_kwh == 155 and d.hours == [18, 19, 20]


def test_no_op_has_no_hours():
    d = normalize_one(_ir("no_op"), capacity=200)
    assert d.directive_type == "no_op" and d.hours == [] and not d.applies
