"""Interpreter orchestration with mock providers — fully offline (§4.9)."""
from __future__ import annotations

import pytest

from app.interpreter import clear_cache, interpret
from app.schemas import IRResponse


@pytest.fixture(autouse=True)
def _clear():
    clear_cache()
    yield
    clear_cache()


def ir(entries):
    return IRResponse.model_validate({"interpretations": entries})


def _entry(i=0, dtype="no_op", windows=None, **kw):
    return {"note_index": i, "directive_type": dtype,
            "windows": windows or [], "factor": kw.get("factor"),
            "minimum_energy_kwh": kw.get("minimum_energy_kwh"),
            "reserve_percent_of_capacity": kw.get("reserve_percent_of_capacity"),
            "max_grid_kwh": kw.get("max_grid_kwh"), "explanation": ""}


def seq_provider(responses):
    """Provider that yields each response in turn; 'raise' triggers an exception."""
    state = {"i": 0}

    def p(notes, repair):
        r = responses[state["i"]]
        state["i"] += 1
        if r == "raise":
            raise RuntimeError("provider down")
        return ir(r)

    p.state = state
    return p


def test_success_first_provider():
    prov = seq_provider([[_entry(0, "solar_reduction",
                                 [{"start_hour": 13, "end_hour": 15}], factor=0.2)]])
    directives, degraded = interpret(["Solar to 20% 1-3 PM"], 200, providers=[prov])
    assert not degraded
    assert directives[0].directive_type == "solar_reduction"
    assert directives[0].hours == [13, 14]


def test_failover_to_second_provider():
    p1 = seq_provider(["raise"])
    p2 = seq_provider([[_entry(0, "no_charge_window", [{"start_hour": 2, "end_hour": 5}])]])
    directives, degraded = interpret(["no charge 2-5 AM"], 200, providers=[p1, p2])
    assert not degraded
    assert directives[0].directive_type == "no_charge_window"
    assert directives[0].hours == [2, 3, 4]


def test_repair_after_guardrail_violation():
    # first response has factor=20 (percentage error) -> guardrail fails -> repair
    bad = [_entry(0, "solar_reduction", [{"start_hour": 13, "end_hour": 15}], factor=20)]
    good = [_entry(0, "solar_reduction", [{"start_hour": 13, "end_hour": 15}], factor=0.2)]
    prov = seq_provider([bad, good])
    directives, degraded = interpret(["Solar 1-3 PM"], 200, providers=[prov])
    assert not degraded
    assert directives[0].factor == 0.2


def test_all_fail_uses_rule_fallback():
    prov = seq_provider(["raise", "raise"])
    directives, degraded = interpret(["Do not charge the battery between 2 PM and 4 PM."],
                                     200, providers=[prov], enable_fallback=True)
    assert degraded
    assert directives[0].directive_type == "no_charge_window"


def test_all_fail_no_fallback_gives_noop():
    prov = seq_provider(["raise"])
    directives, degraded = interpret(["anything"], 200, providers=[prov],
                                     enable_fallback=False)
    assert degraded
    assert directives[0].directive_type == "no_op"


def test_garbage_then_fallback():
    # provider keeps returning guardrail-failing output -> exhausts repair -> fallback
    bad = [_entry(0, "solar_reduction", [{"start_hour": 13, "end_hour": 15}], factor=99)]
    prov = seq_provider([bad, bad, bad, bad])
    directives, degraded = interpret(["Solar panels to nonsense 1-3 PM"], 200,
                                     providers=[prov], enable_fallback=True)
    assert degraded  # fell through to fallback


def test_cache_hit_avoids_second_call():
    prov = seq_provider([[_entry(0, "no_op")], [_entry(0, "no_op")]])
    interpret(["same note"], 200, providers=[prov])
    interpret(["same note"], 200, providers=[prov])
    assert prov.state["i"] == 1  # provider called only once; second was cached


def test_multi_note_mapping():
    entries = [
        _entry(0, "solar_reduction", [{"start_hour": 10, "end_hour": 12}], factor=0.5),
        _entry(1, "no_op"),
        _entry(2, "max_grid_window", [{"start_hour": 19, "end_hour": 22}], max_grid_kwh=180),
    ]
    prov = seq_provider([entries])
    directives, _ = interpret(["a", "b", "c"], 200, providers=[prov])
    assert [d.directive_type for d in directives] == \
        ["solar_reduction", "no_op", "max_grid_window"]
    assert [d.note_index for d in directives] == [0, 1, 2]
