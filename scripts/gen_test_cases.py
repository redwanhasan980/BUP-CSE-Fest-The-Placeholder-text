"""Generate a large battery of test scenarios in the organizer's JSON format.

Produces two artifacts under tests/data/ and examples/:
  - generated_cases.json          (organizer schema: id/label/input/expected_output)
  - GridWise.postman_collection.json  (importable Postman collection; one POST each)

The `input` blocks are the payloads you POST to /optimize-energy.
`expected_output` is computed by OUR solver from directives we build by
construction, then re-verified so every plan honors its own directives. It is a
regression/reference oracle (self-consistent), not an independent judge answer.

Run (venv active, repo root):
  python scripts/gen_test_cases.py            # ~120 cases
  python scripts/gen_test_cases.py -n 150
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.directives import Directive, compute_effective_params  # noqa: E402
from app.engine import run_optimization  # noqa: E402
from app.schemas import Battery, HourEntry  # noqa: E402
from app.summary import build_summary  # noqa: E402
from app.verifier import verify  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]

# --- Distractor notes (must interpret as no_op) --------------------------------
DISTRACTORS = [
    "The sports office moved next month's registration deadline.",
    "Cafeteria will serve a special lunch menu tomorrow.",
    "Reminder: quarterly fire drill is scheduled for next week.",
    "The parking lot near Gate 3 will be repainted this weekend.",
    "IT is rolling out new email signatures across departments.",
    "Library extends its opening hours during exam season.",
    "A guest lecture on renewable policy is planned for Friday.",
    "The HR portal will undergo a branding refresh next quarter.",
]

# --- 24h base profiles: (demand, solar, tariff) --------------------------------
def _profile(seed: int):
    r = random.Random(seed)
    base_d = r.choice([80, 90, 100, 110])
    demand, solar, tariff = [], [], []
    for h in range(24):
        # demand: low overnight, peaks morning + evening
        peak = 60 * (max(0, 1 - abs(h - 9) / 6) + 1.3 * max(0, 1 - abs(h - 19) / 5))
        demand.append(round(base_d + peak + r.uniform(-8, 8)))
        # solar: bell curve centered near noon
        s = 190 * max(0.0, 1 - abs(h - 12.5) / 6.5)
        solar.append(round(max(0.0, s + r.uniform(-10, 10))) if 6 <= h <= 18 else 0)
        # tariff: cheap at night, dearer at peaks
        t = 5 + 6 * max(0, 1 - abs(h - 9) / 7) + 8 * max(0, 1 - abs(h - 19) / 5)
        tariff.append(round(t + r.uniform(-1, 1)))
    return demand, solar, tariff


def _battery(seed: int) -> dict:
    r = random.Random(seed * 7 + 1)
    cap = r.choice([180, 200, 220, 240, 260])
    return {
        "capacity_kwh": cap,
        "initial_energy_kwh": round(cap * r.choice([0.4, 0.5, 0.6])),
        "minimum_energy_kwh": round(cap * r.choice([0.15, 0.2, 0.25])),
        "max_charge_kwh_per_hour": r.choice([40, 50, 60]),
        "max_discharge_kwh_per_hour": r.choice([40, 50, 60]),
    }


def _hours_from_window(start: int, end: int) -> list[int]:
    """Start-inclusive, end-exclusive; end==24 means midnight; supports wrap."""
    if end == start:
        return []
    if end > start:
        return list(range(start, end))
    return sorted(set(range(start, 24)) | set(range(0, end)))  # wraparound


def _ampm(h: int) -> str:
    if h == 0 or h == 24:
        return "midnight"
    if h == 12:
        return "noon"
    suf = "AM" if h < 12 else "PM"
    hh = h if 1 <= h <= 12 else h - 12
    return f"{hh} {suf}"


# --- Directive builders: return (note_text, Directive|None) ---------------------
def d_solar(note_index, r):
    start = r.randint(9, 13)
    end = start + r.randint(2, 4)
    hours = _hours_from_window(start, end)
    style = r.randint(0, 3)
    if style == 0:
        p = r.choice([10, 20, 25, 30, 40])
        note = f"Panels are being cleaned from {_ampm(start)} until {_ampm(end)}; treat usable solar as about {p}% of the forecast."
        factor = p / 100
    elif style == 1:
        q = r.choice([50, 60, 70, 80, 90])
        note = f"Expect a {q}% reduction in usable solar between {_ampm(start)} and {_ampm(end)} due to haze."
        factor = (100 - q) / 100
    elif style == 2:
        p = r.choice([15, 20, 35])
        note = f"During {_ampm(start)}-{_ampm(end)}, solar output drops to {p}% of normal."
        factor = p / 100
    else:
        note = f"Shade from the new building cuts usable solar in half from {_ampm(start)} to {_ampm(end)}."
        factor = 0.5
    d = Directive(note_index, "solar_reduction", hours=hours, factor=round(factor, 4),
                  explanation=f"Usable solar scaled to {factor:.2f} during hours {hours}.")
    return note, d


def d_reserve(note_index, r, battery):
    start = r.randint(17, 21)
    end = min(24, start + r.randint(2, 4))
    hours = _hours_from_window(start, end)
    cap = battery["capacity_kwh"]
    if r.random() < 0.5:
        pct = r.choice([40, 50, 60])
        kwh = round(cap * pct / 100)
        note = f"Keep the battery at no less than {pct}% of capacity from {_ampm(start)} to {_ampm(end)} for the evening event."
    else:
        kwh = r.choice([90, 110, 120, 130])
        kwh = min(kwh, round(cap * 0.7))
        note = f"Maintain at least {kwh} kWh in the battery between {_ampm(start)} and {_ampm(end)}."
    d = Directive(note_index, "minimum_battery_reserve", hours=hours,
                  minimum_energy_kwh=float(kwh),
                  explanation=f"Reserve >= {kwh} kWh during hours {hours}.")
    return note, d


def d_nocharge(note_index, r):
    start = r.randint(0, 5)
    end = start + r.randint(2, 4)
    hours = _hours_from_window(start, end)
    note = f"Do not charge the battery from {_ampm(start)} until {_ampm(end)} during scheduled maintenance."
    d = Directive(note_index, "no_charge_window", hours=hours,
                  explanation=f"Charging disabled during hours {hours}.")
    return note, d


def d_nodischarge(note_index, r):
    start = r.randint(6, 15)
    end = start + r.randint(2, 4)
    hours = _hours_from_window(start, end)
    note = f"Hold the battery — no discharging — from {_ampm(start)} to {_ampm(end)} to protect the cells."
    d = Directive(note_index, "no_discharge_window", hours=hours,
                  explanation=f"Discharging disabled during hours {hours}.")
    return note, d


def d_maxgrid(note_index, r, demand):
    start = r.randint(18, 21)
    end = min(24, start + r.randint(2, 4))
    hours = _hours_from_window(start, end)
    peak = max(demand[h] for h in hours)
    cap = round(peak + r.choice([0, 10, 20]))  # feasible: grid alone can meet demand
    note = f"Grid import must not exceed {cap} kWh in any hour from {_ampm(start)} until {_ampm(end)} (transformer limit)."
    d = Directive(note_index, "max_grid_window", hours=hours, max_grid_kwh=float(cap),
                  explanation=f"Grid import capped at {cap} kWh during hours {hours}.")
    return note, d


def d_noop(note_index, r):
    return r.choice(DISTRACTORS), Directive(note_index, "no_op",
                                            explanation="No effect on today's schedule.")


def build_case(idx: int):
    r = random.Random(1000 + idx)
    demand, solar, tariff = _profile(idx)
    battery = _battery(idx)
    hours = [{"hour": h, "demand_kwh": demand[h], "solar_kwh": solar[h],
              "tariff_bdt_per_kwh": tariff[h]} for h in range(24)]

    n_notes = r.choice([1, 1, 2, 2, 3, 3])
    builders = ["solar", "reserve", "nocharge", "nodischarge", "maxgrid", "noop"]
    chosen = r.sample(builders, k=min(n_notes, len(builders)))
    # guarantee at least one non-distractor in multi-note cases
    if n_notes > 1 and all(c == "noop" for c in chosen):
        chosen[0] = "solar"

    notes, directives = [], []
    for i, kind in enumerate(chosen):
        if kind == "solar":
            note, d = d_solar(i, r)
        elif kind == "reserve":
            note, d = d_reserve(i, r, battery)
        elif kind == "nocharge":
            note, d = d_nocharge(i, r)
        elif kind == "nodischarge":
            note, d = d_nodischarge(i, r)
        elif kind == "maxgrid":
            note, d = d_maxgrid(i, r, demand)
        else:
            note, d = d_noop(i, r)
        notes.append(note)
        directives.append(d)

    scenario_id = f"GEN-{idx:03d}"
    battery_obj = Battery(**battery)
    hour_objs = [HourEntry(**h) for h in hours]

    plan = run_optimization(hour_objs, battery_obj, directives)

    # Re-verify the plan honors the stated directives (drop inconsistent cases).
    p = compute_effective_params(hour_objs, battery_obj, [d for d in directives if d.applies])
    if verify(p, plan):
        return None

    interp = [{
        "note_index": d.note_index,
        "applies": d.applies,
        "directive_type": d.directive_type,
        "structured_adjustment": d.structured_adjustment(),
        "explanation": d.explanation,
    } for d in directives]

    label = " + ".join(dict.fromkeys(
        d.directive_type for d in directives if d.applies) or ["no_op"])

    return {
        "id": scenario_id,
        "label": label,
        "input": {
            "scenario_id": scenario_id,
            "operator_notes": notes,
            "hours": hours,
            "battery": battery,
        },
        "expected_output": {
            "scenario_id": scenario_id,
            "directive_interpretation": interp,
            "hourly_plan": [e.model_dump() for e in plan.hourly_plan],
            "total_grid_kwh": plan.total_grid_kwh,
            "total_cost_bdt": plan.total_cost_bdt,
            "peak_grid_kwh": plan.peak_grid_kwh,
            "plan_summary": build_summary(directives, plan),
        },
    }


def to_postman(cases: list[dict], base_url: str) -> dict:
    items = [{
        "name": f"{c['id']} — {c['label']}",
        "request": {
            "method": "POST",
            "header": [{"key": "Content-Type", "value": "application/json"}],
            "body": {"mode": "raw",
                     "raw": json.dumps(c["input"], indent=2)},
            "url": {"raw": "{{base_url}}/optimize-energy",
                    "host": ["{{base_url}}"], "path": ["optimize-energy"]},
        },
    } for c in cases]
    items.insert(0, {
        "name": "GET /health",
        "request": {"method": "GET",
                    "url": {"raw": "{{base_url}}/health",
                            "host": ["{{base_url}}"], "path": ["health"]}},
    })
    return {
        "info": {"name": "GridWise LLM — generated cases",
                 "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
        "item": items,
        "variable": [{"key": "base_url", "value": base_url}],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--count", type=int, default=120)
    ap.add_argument("--base-url", default="http://localhost:8000")
    args = ap.parse_args()

    cases, i = [], 0
    while len(cases) < args.count and i < args.count * 3:
        try:
            c = build_case(i)
            if c is not None:
                cases.append(c)
        except Exception as exc:
            print(f"skip idx {i}: {type(exc).__name__}: {exc}")
        i += 1

    counts: dict[str, int] = {}
    for c in cases:
        for d in c["expected_output"]["directive_interpretation"]:
            counts[d["directive_type"]] = counts.get(d["directive_type"], 0) + 1

    data = {"_meta": {"generated": True, "count": len(cases),
                      "note": "expected_output computed by our own solver; re-verified."},
            "cases": cases}

    out_cases = ROOT / "tests" / "data" / "generated_cases.json"
    out_post = ROOT / "examples" / "GridWise.postman_collection.json"
    out_cases.write_text(json.dumps(data, indent=2), encoding="utf-8")
    out_post.write_text(json.dumps(to_postman(cases, args.base_url), indent=2), encoding="utf-8")

    print(f"wrote {len(cases)} cases -> {out_cases}")
    print(f"wrote Postman collection -> {out_post}")
    print("directive coverage:", counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
