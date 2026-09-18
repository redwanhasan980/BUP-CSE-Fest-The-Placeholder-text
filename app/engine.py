from __future__ import annotations

from app.directives import Directive, compute_effective_params
from app.errors import ApiError
from app.optimizer import solve
from app.plan import BuiltPlan, build_plan
from app.schemas import Battery, HourEntry
from app.verifier import verify


def run_optimization(
    hours: list[HourEntry], battery: Battery, directives: list[Directive]
) -> BuiltPlan:
    """Full deterministic path: effective params -> LP -> plan -> verify.

    Implements the infeasibility recovery ladder (SRS §9.2). Judge scenarios
    are guaranteed feasible, so the drop/base paths are defensive only.
    """
    applicable = [d for d in directives if d.applies]

    p = compute_effective_params(hours, battery, applicable)
    sol = solve(p)

    if not sol.feasible:
        base_params = compute_effective_params(hours, battery, [])
        if not solve(base_params).feasible:
            raise ApiError(422, "INFEASIBLE_SCENARIO",
                           "The base scenario has no feasible schedule")
        kept = [d for d in applicable
                if solve(compute_effective_params(hours, battery, [d])).feasible]
        p = compute_effective_params(hours, battery, kept)
        sol = solve(p)
        if not sol.feasible:
            p = base_params
            sol = solve(base_params)

    plan = build_plan(p, sol)
    reasons = verify(p, plan)
    if reasons:
        raise ApiError(500, "PLAN_VERIFICATION_FAILED",
                       "The generated plan failed internal verification")
    return plan
