from __future__ import annotations

from app.directives import Directive, compute_effective_params
from app.engine import run_optimization
from app.schemas import Battery, HourEntry
from app.verifier import verify


def _hours(demand=100.0, solar=0.0, tariff=10.0):
    return [HourEntry(hour=h, demand_kwh=demand, solar_kwh=solar,
                      tariff_bdt_per_kwh=tariff) for h in range(24)]


def _battery(cap=200, init=100, mn=40, cr=50, dr=50):
    return Battery(capacity_kwh=cap, initial_energy_kwh=init, minimum_energy_kwh=mn,
                   max_charge_kwh_per_hour=cr, max_discharge_kwh_per_hour=dr)


def _run_ok(hours, battery, directives):
    plan = run_optimization(hours, battery, directives)
    p = compute_effective_params(hours, battery, [d for d in directives if d.applies])
    assert verify(p, plan) == []
    return plan


def test_zero_solar_all_day():
    _run_ok(_hours(solar=0.0), _battery(), [])


def test_zero_capacity_battery():
    b = _battery(cap=0, init=0, mn=0, cr=0, dr=0)
    plan = _run_ok(_hours(solar=30.0), b, [])
    assert all(e.battery_action == "idle" for e in plan.hourly_plan)


def test_negative_tariff_charges():
    # one very cheap (negative) hour should attract charging
    hs = _hours(tariff=10.0)
    hs[3] = HourEntry(hour=3, demand_kwh=100, solar_kwh=0, tariff_bdt_per_kwh=-5)
    plan = _run_ok(hs, _battery(), [])
    assert plan.hourly_plan[3].battery_action == "charge"


def test_overlapping_solar_factors_multiply():
    hs = _hours(solar=100.0)
    d1 = Directive(0, "solar_reduction", hours=[10], factor=0.5)
    d2 = Directive(1, "solar_reduction", hours=[10], factor=0.5)
    p = compute_effective_params(hs, _battery(), [d1, d2])
    assert abs(p.eff_solar[10] - 25.0) < 1e-9  # 100 * 0.5 * 0.5


def test_overlapping_reserves_take_max():
    hs = _hours()
    d1 = Directive(0, "minimum_battery_reserve", hours=[18], minimum_energy_kwh=90)
    d2 = Directive(1, "minimum_battery_reserve", hours=[18], minimum_energy_kwh=120)
    p = compute_effective_params(hs, _battery(cap=200, init=150), [d1, d2])
    assert p.emin[18] == 120


def test_overlapping_caps_take_min():
    hs = _hours()
    d1 = Directive(0, "max_grid_window", hours=[19], max_grid_kwh=180)
    d2 = Directive(1, "max_grid_window", hours=[19], max_grid_kwh=155)
    p = compute_effective_params(hs, _battery(), [d1, d2])
    assert p.gmax[19] == 155


def test_reserve_below_base_min_uses_base():
    hs = _hours()
    d = Directive(0, "minimum_battery_reserve", hours=[18], minimum_energy_kwh=10)
    p = compute_effective_params(hs, _battery(mn=40), [d])
    assert p.emin[18] == 40  # base minimum wins


def test_recovery_ladder_returns_plan_on_impossible_combo():
    # grid capped to 0 AND no discharge at the same hour with demand>0, no solar
    hs = _hours(demand=100.0, solar=0.0)
    d1 = Directive(0, "max_grid_window", hours=[0], max_grid_kwh=0)
    d2 = Directive(1, "no_discharge_window", hours=[0])
    plan = run_optimization(hs, _battery(), [d1, d2])  # must not raise
    assert len(plan.hourly_plan) == 24
