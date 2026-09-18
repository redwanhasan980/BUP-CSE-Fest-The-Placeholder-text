"""Phase C milestone: with ground-truth directives, the LP must reproduce the
reference optimal cost on all 10 public cases, and every plan must verify."""
from __future__ import annotations

import pytest

from app.directives import compute_effective_params
from app.engine import run_optimization
from app.verifier import verify
from tests.samples import ground_truth_directives, load_cases, request_of

CASES = load_cases()
IDS = [c["id"] for c in CASES]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_reference_cost_match(case):
    req = request_of(case)
    directives = ground_truth_directives(case)
    plan = run_optimization(req.hours, req.battery, directives)

    exp = case["expected_output"]
    assert abs(plan.total_cost_bdt - exp["total_cost_bdt"]) <= 0.01, (
        f"{case['id']} cost {plan.total_cost_bdt} vs ref {exp['total_cost_bdt']}")
    assert abs(plan.total_grid_kwh - exp["total_grid_kwh"]) <= 0.01
    assert abs(plan.peak_grid_kwh - exp["peak_grid_kwh"]) <= 0.01


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_plan_verifies(case):
    req = request_of(case)
    directives = ground_truth_directives(case)
    plan = run_optimization(req.hours, req.battery, directives)
    p = compute_effective_params(req.hours, req.battery,
                                 [d for d in directives if d.applies])
    assert verify(p, plan) == []


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_no_simultaneous_charge_discharge(case):
    req = request_of(case)
    plan = run_optimization(req.hours, req.battery, ground_truth_directives(case))
    for e in plan.hourly_plan:
        if e.battery_action == "idle":
            assert e.battery_kwh == 0


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_neutrality(case):
    req = request_of(case)
    plan = run_optimization(req.hours, req.battery, ground_truth_directives(case))
    assert abs(plan.hourly_plan[-1].battery_energy_after_kwh
               - req.battery.initial_energy_kwh) <= 0.01
