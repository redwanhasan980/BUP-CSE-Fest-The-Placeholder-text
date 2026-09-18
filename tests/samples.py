"""Helpers to load the public sample pack and build ground-truth directives."""
from __future__ import annotations

import json
import pathlib

from app.directives import Directive
from app.schemas import ScenarioRequest

_DATA = pathlib.Path(__file__).parent / "data" / "public_sample_cases.json"


def load_cases() -> list[dict]:
    with open(_DATA, encoding="utf-8") as f:
        return json.load(f)["cases"]


def ground_truth_directives(case: dict) -> list[Directive]:
    out: list[Directive] = []
    for entry in case["expected_output"]["directive_interpretation"]:
        t = entry["directive_type"]
        sa = entry.get("structured_adjustment") or {}
        out.append(Directive(
            note_index=entry["note_index"],
            directive_type=t,
            hours=list(sa.get("hours", [])),
            factor=sa.get("factor"),
            minimum_energy_kwh=sa.get("minimum_energy_kwh"),
            max_grid_kwh=sa.get("max_grid_kwh"),
            explanation=entry.get("explanation", ""),
        ))
    return out


def request_of(case: dict) -> ScenarioRequest:
    return ScenarioRequest.model_validate(case["input"])


def ground_truth_ir(case: dict) -> dict:
    """Build an IR payload (as an LLM would return) from the expected output,
    so the full pipeline can be exercised offline with a mock provider."""
    interps = []
    for entry in case["expected_output"]["directive_interpretation"]:
        sa = entry.get("structured_adjustment") or {}
        hours = sa.get("hours", [])
        interps.append({
            "note_index": entry["note_index"],
            "directive_type": entry["directive_type"],
            "windows": [{"start_hour": h, "end_hour": h + 1} for h in hours],
            "factor": sa.get("factor"),
            "minimum_energy_kwh": sa.get("minimum_energy_kwh"),
            "reserve_percent_of_capacity": None,
            "max_grid_kwh": sa.get("max_grid_kwh"),
            "explanation": entry.get("explanation", ""),
        })
    return {"interpretations": interps}
