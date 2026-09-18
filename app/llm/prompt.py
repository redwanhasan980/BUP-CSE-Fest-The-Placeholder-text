from __future__ import annotations

import json

SYSTEM_PROMPT = """\
You convert campus energy operator notes into structured directives. You handle \
LANGUAGE ONLY. Deterministic code does all arithmetic and scheduling afterward.

Return a JSON object of the exact form:
{"interpretations": [ <one entry per note, in note_index order> ]}

Each entry has EXACTLY these keys:
  note_index: integer (0-based, matching the input note)
  directive_type: one of
     "solar_reduction", "minimum_battery_reserve", "no_charge_window",
     "no_discharge_window", "max_grid_window", "no_op"
  windows: array of {"start_hour": int, "end_hour": int}  (empty [] for no_op)
  factor: number or null
  minimum_energy_kwh: number or null
  reserve_percent_of_capacity: number or null
  max_grid_kwh: number or null
  explanation: short string

TIME RULES (produce windows, never hour lists):
- Windows are start-INCLUSIVE, end-EXCLUSIVE. "1 PM to 3 PM" -> {"start_hour":13,"end_hour":15}.
- Use 24-hour integers. noon=12, midnight as an end = 24, midnight as a start = 0.
- "at 7 PM" / "the 18:00 hour" -> a single-hour window ({"start_hour":19,"end_hour":20}).
- "for N hours starting at X" -> {start:X, end:X+N}.
- "after X" / "from X onward" -> {start:X, end:24}. "before X" / "until X" -> {start:0, end:X}.
- "all day" -> {start:0, end:24}. Crossing midnight is allowed (end < start).
- If AM/PM is missing, infer from context (solar/panels imply daylight hours).

DIRECTIVE RULES:
- solar_reduction: set factor = the usable fraction that REMAINS.
    "drop to 20%" -> 0.2. "80% reduction"/"reduced by 80%"/"loses 80%" -> 0.2.
    "half"/"50% output" -> 0.5. "a quarter"/"25%" -> 0.25. "one-fifth" -> 0.2.
    "no solar"/"panels offline"/"zero output" -> 0.0. factor must be between 0 and 1.
- minimum_battery_reserve: an absolute figure ("at least 90 kWh") -> minimum_energy_kwh=90.
    A percentage of capacity ("50% of capacity","half-charged") -> reserve_percent_of_capacity=50
    and leave minimum_energy_kwh null. Do NOT convert percentages yourself.
- no_charge_window: "do not charge","charger isolated","charging disabled/off". Only windows.
- no_discharge_window: "must not discharge","discharge disabled","don't draw from the battery".
- max_grid_window: "grid must not exceed 155 kWh","capped at 155","limited to 155" -> max_grid_kwh=155.
    A power figure over a 1-hour step ("155 kW limit") -> max_grid_kwh=155.

no_op RULES (do NOT invent a constraint):
- Note unrelated to energy (cafeteria, library, registration, clubs, room bookings, seminars).
- Note about a different period ("next week","next month","last week","yesterday").
- Note that cancels/negates a prior restriction ("the 2-4 PM maintenance is cancelled").
- Energy-related but not one of the six types (a demand change, a tariff change, a general remark).
For no_op: windows=[] and every numeric field null.

An energy constraint stated for "tomorrow" DOES apply (the scenario is the next 24 hours).
Never output changes to demand, solar, tariff, or battery limits. Never add extra keys.
Output ONLY the JSON object, no prose.
"""

# Synthetic few-shots: paraphrased, different numbers/hours than the public pack.
_FEWSHOT = [
    (
        ["Rooftop PV will run at about 40% of forecast while crews inspect the array from 9 AM to 11 AM.",
         "The debate club moved its meeting to Thursday."],
        {"interpretations": [
            {"note_index": 0, "directive_type": "solar_reduction",
             "windows": [{"start_hour": 9, "end_hour": 11}], "factor": 0.4,
             "minimum_energy_kwh": None, "reserve_percent_of_capacity": None,
             "max_grid_kwh": None, "explanation": "PV limited to 40% during inspection."},
            {"note_index": 1, "directive_type": "no_op", "windows": [], "factor": None,
             "minimum_energy_kwh": None, "reserve_percent_of_capacity": None,
             "max_grid_kwh": None, "explanation": "Club scheduling; no energy effect."},
        ]},
    ),
    (
        ["Hold the battery at no less than 30% of capacity between 7 PM and 10 PM.",
         "Keep grid draw at or below 210 kWh from 8 PM to 11 PM for the substation test."],
        {"interpretations": [
            {"note_index": 0, "directive_type": "minimum_battery_reserve",
             "windows": [{"start_hour": 19, "end_hour": 22}], "factor": None,
             "minimum_energy_kwh": None, "reserve_percent_of_capacity": 30,
             "max_grid_kwh": None, "explanation": "Reserve 30% of capacity in the evening window."},
            {"note_index": 1, "directive_type": "max_grid_window",
             "windows": [{"start_hour": 20, "end_hour": 23}], "factor": None,
             "minimum_energy_kwh": None, "reserve_percent_of_capacity": None,
             "max_grid_kwh": 210, "explanation": "Grid capped at 210 kWh during the test."},
        ]},
    ),
    (
        ["Battery charging stays offline from 3 AM until 6 AM for wiring work."],
        {"interpretations": [
            {"note_index": 0, "directive_type": "no_charge_window",
             "windows": [{"start_hour": 3, "end_hour": 6}], "factor": None,
             "minimum_energy_kwh": None, "reserve_percent_of_capacity": None,
             "max_grid_kwh": None, "explanation": "No charging during wiring work."},
        ]},
    ),
]


def build_messages(notes: list[str], repair_reasons: list[str] | None = None) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for user_notes, ir in _FEWSHOT:
        messages.append({"role": "user", "content": _format_notes(user_notes)})
        messages.append({"role": "assistant", "content": json.dumps(ir)})
    content = _format_notes(notes)
    if repair_reasons:
        content += ("\n\nYour previous answer failed these deterministic checks. "
                    "Fix them and return corrected JSON:\n- " + "\n- ".join(repair_reasons))
    messages.append({"role": "user", "content": content})
    return messages


def _format_notes(notes: list[str]) -> str:
    lines = ["Interpret these operator notes:"]
    for i, n in enumerate(notes):
        lines.append(f"[note_index {i}] {n}")
    return "\n".join(lines)
