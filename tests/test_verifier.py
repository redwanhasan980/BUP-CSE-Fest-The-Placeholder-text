"""Every deliberate corruption of a valid plan must be caught (§4.4)."""
from __future__ import annotations

import copy

import pytest

from app.directives import compute_effective_params
from app.engine import run_optimization
from app.verifier import verify
from tests.samples import ground_truth_directives, load_cases, request_of

CASES = {c["id"]: c for c in load_cases()}


def build(case_id):
    case = CASES[case_id]
    req = request_of(case)
    directives = ground_truth_directives(case)
    plan = run_optimization(req.hours, req.battery, directives)
    p = compute_effective_params(req.hours, req.battery,
                                 [d for d in directives if d.applies])
    return req, p, plan


def has(reasons, code):
    return any(code in r for r in reasons)


def test_valid_plan_has_no_reasons():
    _, p, plan = build("SAMPLE-01")
    assert verify(p, plan) == []


def test_v01_hour_set_corruption():
    _, p, plan = build("SAMPLE-01")
    bad = copy.deepcopy(plan)
    bad.hourly_plan[5].hour = 99
    assert has(verify(p, bad), "V-01")


def test_v04_balance():
    _, p, plan = build("SAMPLE-01")
    bad = copy.deepcopy(plan)
    bad.hourly_plan[5].grid_kwh += 0.5
    assert has(verify(p, bad), "V-04")


def test_v05_solar_overuse():
    _, p, plan = build("SAMPLE-01")
    bad = copy.deepcopy(plan)
    bad.hourly_plan[12].solar_used_kwh = p.eff_solar[12] + 10  # hour 12 is reduced solar
    assert has(verify(p, bad), "V-05")


def test_v07_above_capacity():
    req, p, plan = build("SAMPLE-01")
    bad = copy.deepcopy(plan)
    bad.hourly_plan[4].battery_energy_after_kwh = req.battery.capacity_kwh + 50
    assert has(verify(p, bad), "V-07")


def test_v07_below_reserve():
    _, p, plan = build("SAMPLE-03")  # has minimum_battery_reserve 100 @ 18-20
    bad = copy.deepcopy(plan)
    bad.hourly_plan[19].battery_energy_after_kwh = 10
    assert has(verify(p, bad), "V-07")


def test_v08_rate_limit():
    req, p, plan = build("SAMPLE-01")
    bad = copy.deepcopy(plan)
    e = bad.hourly_plan[6]
    e.battery_action = "charge"
    e.battery_kwh = req.battery.max_charge_kwh_per_hour + 100
    assert has(verify(p, bad), "V-08")


def test_v09_charge_in_no_charge_window():
    _, p, plan = build("SAMPLE-02")  # no_charge_window hours [2,3,4]
    bad = copy.deepcopy(plan)
    e = bad.hourly_plan[3]
    e.battery_action = "charge"
    e.battery_kwh = 10
    assert has(verify(p, bad), "V-09")


def test_v09_discharge_in_no_discharge_window():
    _, p, plan = build("SAMPLE-04")  # no_discharge_window hours [18,19]
    bad = copy.deepcopy(plan)
    e = bad.hourly_plan[18]
    e.battery_action = "discharge"
    e.battery_kwh = 10
    assert has(verify(p, bad), "V-09")


def test_v10_grid_cap():
    _, p, plan = build("SAMPLE-05")  # max_grid_window 155 @ 18-20
    bad = copy.deepcopy(plan)
    bad.hourly_plan[19].grid_kwh = 300
    assert has(verify(p, bad), "V-10")


def test_v03_idle_nonzero():
    _, p, plan = build("SAMPLE-01")
    bad = copy.deepcopy(plan)
    e = next(e for e in bad.hourly_plan if e.battery_action == "idle")
    e.battery_kwh = 5
    assert has(verify(p, bad), "V-03")


def test_v11_neutrality():
    _, p, plan = build("SAMPLE-01")
    bad = copy.deepcopy(plan)
    bad.hourly_plan[23].battery_energy_after_kwh += 25
    assert has(verify(p, bad), "V-11")


def test_v12_totals_mismatch():
    _, p, plan = build("SAMPLE-01")
    bad = copy.deepcopy(plan)
    bad.total_cost_bdt += 100
    assert has(verify(p, bad), "V-12")


def test_tolerance_not_falsely_flagged():
    _, p, plan = build("SAMPLE-01")
    ok = copy.deepcopy(plan)
    ok.total_cost_bdt += 0.005  # within 0.01 tolerance
    assert verify(p, ok) == []
