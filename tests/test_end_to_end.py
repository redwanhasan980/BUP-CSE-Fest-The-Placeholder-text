"""Full pipeline offline: mock provider returns ground-truth IR, then the real
normalizer -> guardrails -> optimizer -> verifier -> response assembly runs.
Independently replays the returned plan (§4.3 downstream application)."""
from __future__ import annotations

import pytest

from app.directives import Directive, compute_effective_params
from app.pipeline import process
from app.plan import BuiltPlan
from app.schemas import IRResponse
from app.verifier import verify
from tests.samples import ground_truth_ir, load_cases, request_of

CASES = load_cases()
IDS = [c["id"] for c in CASES]


def mock_provider(ir_payload):
    def p(notes, repair):
        return IRResponse.model_validate(ir_payload)
    return p


def _directives_from_response(resp) -> list[Directive]:
    out = []
    for e in resp.directive_interpretation:
        sa = e.structured_adjustment or {}
        out.append(Directive(
            note_index=e.note_index, directive_type=e.directive_type,
            hours=list(sa.get("hours", [])), factor=sa.get("factor"),
            minimum_energy_kwh=sa.get("minimum_energy_kwh"),
            max_grid_kwh=sa.get("max_grid_kwh"),
        ))
    return out


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_pipeline_matches_reference_and_verifies(case):
    req = request_of(case)
    prov = mock_provider(ground_truth_ir(case))
    resp, meta = process(req, providers=[prov], use_cache=False)

    exp = case["expected_output"]
    assert resp.scenario_id == case["id"]
    assert abs(resp.total_cost_bdt - exp["total_cost_bdt"]) <= 0.01
    assert abs(resp.total_grid_kwh - exp["total_grid_kwh"]) <= 0.01
    assert abs(resp.peak_grid_kwh - exp["peak_grid_kwh"]) <= 0.01

    # one entry per note in order
    assert [e.note_index for e in resp.directive_interpretation] == \
        list(range(len(req.operator_notes)))

    # independent replay of the returned plan
    directives = _directives_from_response(resp)
    p = compute_effective_params(req.hours, req.battery,
                                 [d for d in directives if d.applies])
    built = BuiltPlan(resp.hourly_plan, resp.total_grid_kwh,
                      resp.total_cost_bdt, resp.peak_grid_kwh)
    assert verify(p, built) == []


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_interpretation_matches_expected(case):
    req = request_of(case)
    prov = mock_provider(ground_truth_ir(case))
    resp, _ = process(req, providers=[prov], use_cache=False)

    for got, exp in zip(resp.directive_interpretation,
                        case["expected_output"]["directive_interpretation"]):
        assert got.directive_type == exp["directive_type"]
        assert got.applies == exp["applies"]
        if exp["directive_type"] == "no_op":
            assert got.structured_adjustment is None
        else:
            g, e = got.structured_adjustment, exp["structured_adjustment"]
            assert g["hours"] == e["hours"]
            for k in ("factor", "minimum_energy_kwh", "max_grid_kwh"):
                if k in e:
                    assert abs(g[k] - e[k]) <= 0.01
