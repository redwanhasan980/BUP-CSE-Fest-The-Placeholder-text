"""Manual live check: interpret a few notes via the configured LLM provider(s).
Run: python scripts/live_llm_check.py
"""
from __future__ import annotations

import sys

from app.interpreter import interpret

NOTES = [
    ["PV production will drop to about 20% between 13:00 and 15:00.",
     "The library extends its hours next week."],
    ["Hold the battery at no less than 40% of capacity from 7 PM to 10 PM."],
    ["Keep grid import at or below 175 kWh from 6 PM until 9 PM for the feeder test."],
]


def main() -> int:
    for notes in NOTES:
        directives, degraded = interpret(notes, capacity=200, use_cache=False)
        tag = "DEGRADED" if degraded else "LLM"
        print(f"\n[{tag}] notes={notes}")
        for d in directives:
            print(f"  #{d.note_index} {d.directive_type} hours={d.hours} "
                  f"factor={d.factor} reserve={d.minimum_energy_kwh} cap={d.max_grid_kwh}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
