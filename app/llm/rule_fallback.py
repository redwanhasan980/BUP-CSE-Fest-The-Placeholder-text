"""Degraded-mode deterministic parser. Used ONLY when every LLM attempt fails.
Conservative by design: emits a directive only when confident, else no_op.
Never invents demand/tariff/battery changes (FR-LLM-09)."""
from __future__ import annotations

import re

from app.directives import Directive
from app.normalizer import expand_window

_WORDNUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
_FRACTION = {"half": 0.5, "quarter": 0.25, "third": 1 / 3, "one-fifth": 0.2,
             "fifth": 0.2, "one-quarter": 0.25, "three-quarters": 0.75}

_OTHER_PERIOD = re.compile(
    r"\b(next week|next month|last week|last month|yesterday|tomorrow'?s? (?:menu|meeting|deadline)|"
    r"next year|earlier this week)\b")
_CANCELLED = re.compile(r"\b(cancel(?:led|ed)?|called off|no longer|rescheduled|postponed|"
                        r"has been lifted|is lifted|resumed normal)\b")


def _num_token(tok: str):
    tok = tok.strip().lower()
    if tok in _WORDNUM:
        return _WORDNUM[tok]
    m = re.match(r"^(\d{1,2})", tok)
    return int(m.group(1)) if m else None


def _to24(h: int, ampm: str | None, daylight: bool) -> int:
    if ampm == "pm" and h != 12:
        return h + 12
    if ampm == "am" and h == 12:
        return 0
    if ampm is None and daylight and 1 <= h <= 11:
        return h + 12
    return h


def _windows(text: str, daylight: bool) -> list[tuple[int, int]]:
    t = text.lower()
    if re.search(r"\b(all day|whole day|entire day|throughout the day)\b", t):
        return [(0, 24)]

    def kw(word):  # named clock keywords
        return {"noon": 12, "midday": 12, "midnight": None}.get(word)

    wins: list[tuple[int, int]] = []

    # "for N hours starting at/from X"
    for m in re.finditer(r"for\s+(\w+)\s+hours?\s+(?:starting\s+)?(?:at|from)\s+(\w+)\s*(am|pm)?", t):
        n = _num_token(m.group(1))
        x = _num_token(m.group(2))
        if n and x is not None:
            s = _to24(x, m.group(3), daylight)
            wins.append((s, s + n))

    # ranges: "X (am/pm) to/until/-/and Y (am/pm)", "between X and Y", "from X to Y"
    rng = re.compile(
        r"(?:between\s+|from\s+)?"
        r"(noon|midday|midnight|\d{1,2}(?::\d{2})?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
        r"\s*(am|pm)?\s*(?:to|until|till|through|-|–|and)\s*"
        r"(noon|midday|midnight|\d{1,2}(?::\d{2})?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
        r"\s*(am|pm)?")
    for m in rng.finditer(t):
        s = _resolve(m.group(1), m.group(2), daylight, is_end=False)
        e = _resolve(m.group(3), m.group(4) or m.group(2), daylight, is_end=True)
        if s is not None and e is not None:
            wins.append((s, e))

    if wins:
        return wins

    # open-ended "after X" / "before X"/"until X"
    m = re.search(r"\b(?:after|from)\s+(\w+)\s*(am|pm)?\s*(?:onward|onwards)?\b", t)
    if m:
        x = _resolve(m.group(1), m.group(2), daylight, is_end=False)
        if x is not None:
            return [(x, 24)]
    m = re.search(r"\b(?:before|until|by)\s+(\w+)\s*(am|pm)?\b", t)
    if m:
        x = _resolve(m.group(1), m.group(2), daylight, is_end=True)
        if x is not None:
            return [(0, x)]

    # single "at X"
    m = re.search(r"\bat\s+(\w+)\s*(am|pm)?\b", t)
    if m:
        x = _resolve(m.group(1), m.group(2), daylight, is_end=False)
        if x is not None:
            return [(x, x + 1)]

    return []


def _resolve(token: str, ampm: str | None, daylight: bool, is_end: bool):
    token = token.strip()
    if token in ("noon", "midday"):
        return 12
    if token == "midnight":
        return 24 if is_end else 0
    if ":" in token:
        token = token.split(":")[0]
    n = _num_token(token)
    if n is None:
        return None
    return _to24(n, ampm, daylight)


def _hours(text: str, daylight: bool) -> list[int]:
    out: set[int] = set()
    for s, e in _windows(text, daylight):
        out.update(expand_window(s, e))
    return sorted(out)


def _factor(text: str) -> float | None:
    t = text.lower()
    if re.search(r"\b(no solar|zero (?:solar|output)|panels? offline|fully offline)\b", t):
        return 0.0
    m = re.search(r"(\d{1,3})\s*%\s*reduction|reduc\w*\s+by\s+(\d{1,3})\s*%|loses?\s+(\d{1,3})\s*%", t)
    if m:
        pct = int(next(g for g in m.groups() if g))
        return max(0.0, 1 - pct / 100.0)
    m = re.search(r"(?:drop|down|fall|reduced|only|about|treat\w*\s+as|to|at)\s*(?:to\s*)?(\d{1,3})\s*%", t)
    if m:
        return int(m.group(1)) / 100.0
    m = re.search(r"(\d{1,3})\s*%", t)
    if m:
        return int(m.group(1)) / 100.0
    for word, val in _FRACTION.items():
        if word in t:
            return val
    return None


def parse_note(note: str, note_index: int, capacity: float) -> Directive:
    t = note.lower()

    if _OTHER_PERIOD.search(t) or _CANCELLED.search(t):
        return Directive(note_index, "no_op", explanation="No effect on today's schedule (degraded parse).")

    solar_ctx = bool(re.search(r"\b(solar|pv|panel|photovoltaic|rooftop)\b", t))

    # no_charge
    if re.search(r"\b(charg\w+)\b", t) and re.search(
            r"\b(no|not|disabled?|isolat\w+|off|offline|unavailable|stop\w*|suspend\w+)\b", t) \
            and "discharg" not in t.split("charg")[0][-4:]:
        hrs = _hours(note, daylight=False)
        if hrs:
            return Directive(note_index, "no_charge_window", hours=hrs,
                             explanation="Charging unavailable (degraded parse).")

    # no_discharge
    if re.search(r"\b(discharg\w+|draw (?:from|down))\b", t) and re.search(
            r"\b(no|not|must not|disabled?|off|prevent\w*|avoid)\b", t):
        hrs = _hours(note, daylight=False)
        if hrs:
            return Directive(note_index, "no_discharge_window", hours=hrs,
                             explanation="Discharge disabled (degraded parse).")

    # minimum reserve
    if re.search(r"\b(reserve|at least|no less than|keep|maintain|above|minimum)\b", t) and \
            re.search(r"\b(battery|charge|stored|kwh|capacity|%)\b", t) and "grid" not in t:
        hrs = _hours(note, daylight=False)
        pct = re.search(r"(\d{1,3})\s*%|half", t)
        kwh = re.search(r"(\d{2,5})\s*kwh", t)
        if hrs and (kwh or pct):
            if kwh:
                val = float(kwh.group(1))
            else:
                frac = 0.5 if "half" in t else int(pct.group(1)) / 100.0
                val = frac * capacity
            return Directive(note_index, "minimum_battery_reserve", hours=hrs,
                             minimum_energy_kwh=val, explanation="Minimum reserve (degraded parse).")

    # max grid
    if re.search(r"\b(grid|import)\b", t) and re.search(
            r"\b(not exceed|exceed|cap\w*|limit\w*|at or below|below|no more than|up to)\b", t):
        hrs = _hours(note, daylight=False)
        kwh = re.search(r"(\d{2,5})\s*k?w", t)
        if hrs and kwh:
            return Directive(note_index, "max_grid_window", hours=hrs,
                             max_grid_kwh=float(kwh.group(1)),
                             explanation="Grid cap (degraded parse).")

    # solar reduction
    if solar_ctx:
        f = _factor(note)
        hrs = _hours(note, daylight=True)
        if f is not None and hrs:
            return Directive(note_index, "solar_reduction", hours=hrs, factor=f,
                             explanation="Solar reduced (degraded parse).")

    return Directive(note_index, "no_op", explanation="Could not confidently interpret (degraded parse).")


def rule_fallback(notes: list[str], capacity: float) -> list[Directive]:
    return [parse_note(n, i, capacity) for i, n in enumerate(notes)]
