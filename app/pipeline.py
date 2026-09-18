from __future__ import annotations

import time
from typing import Optional

from app.config import settings
from app.directives import Directive
from app.engine import run_optimization
from app.interpreter import interpret
from app.llm.client import Provider
from app.schemas import DirectiveInterpretation, OptimizeResponse, ScenarioRequest
from app.summary import build_summary

_TEMPLATE = {
    "solar_reduction": "Usable solar is reduced during the listed hours.",
    "minimum_battery_reserve": "Battery energy is kept at or above the reserve in the listed hours.",
    "no_charge_window": "Battery charging is disabled in the listed hours.",
    "no_discharge_window": "Battery discharging is disabled in the listed hours.",
    "max_grid_window": "Grid import is capped in the listed hours.",
    "no_op": "This note does not affect today's energy schedule.",
}


def _explanation(d: Directive) -> str:
    text = (d.explanation or "").replace("\n", " ").replace("\r", " ").strip()
    if not text:
        text = _TEMPLATE.get(d.directive_type, "")
    return text[:240]


def _interpretation_entries(directives: list[Directive]) -> list[DirectiveInterpretation]:
    return [
        DirectiveInterpretation(
            note_index=d.note_index,
            applies=d.applies,
            directive_type=d.directive_type,
            structured_adjustment=d.structured_adjustment(),
            explanation=_explanation(d),
        )
        for d in sorted(directives, key=lambda x: x.note_index)
    ]


def process(
    req: ScenarioRequest,
    providers: Optional[list[Provider]] = None,
    use_cache: bool = True,
) -> tuple[OptimizeResponse, dict]:
    """Full request pipeline. Returns (response, log_meta). Raises ApiError on
    infeasible scenario or verification failure."""
    start = time.monotonic()
    deadline = start + settings.request_deadline_seconds

    notes = list(req.operator_notes)
    directives, degraded = interpret(
        notes, req.battery.capacity_kwh, providers=providers,
        use_cache=use_cache, deadline=deadline,
    )

    plan = run_optimization(req.hours, req.battery, directives)

    response = OptimizeResponse(
        scenario_id=req.scenario_id,
        directive_interpretation=_interpretation_entries(directives),
        hourly_plan=plan.hourly_plan,
        total_grid_kwh=plan.total_grid_kwh,
        total_cost_bdt=plan.total_cost_bdt,
        peak_grid_kwh=plan.peak_grid_kwh,
        plan_summary=build_summary(directives, plan),
    )
    meta = {
        "scenario_id": req.scenario_id,
        "degraded": degraded,
        "directive_types": [d.directive_type for d in directives],
        "latency_ms": round((time.monotonic() - start) * 1000, 1),
        "total_cost_bdt": plan.total_cost_bdt,
    }
    return response, meta
