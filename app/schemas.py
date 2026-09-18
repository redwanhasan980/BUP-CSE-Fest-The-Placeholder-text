from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HourEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hour: int
    demand_kwh: float
    solar_kwh: float
    tariff_bdt_per_kwh: float


class Battery(BaseModel):
    model_config = ConfigDict(extra="ignore")

    capacity_kwh: float
    initial_energy_kwh: float
    minimum_energy_kwh: float
    max_charge_kwh_per_hour: float
    max_discharge_kwh_per_hour: float


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scenario_id: str = Field(min_length=1)
    operator_notes: list[str] = Field(min_length=1, max_length=3)
    hours: list[HourEntry] = Field(min_length=24, max_length=24)
    battery: Battery

    @field_validator("scenario_id")
    @classmethod
    def _scenario_id_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("scenario_id must be non-empty")
        return v

    @field_validator("operator_notes")
    @classmethod
    def _notes_nonempty(cls, v: list[str]) -> list[str]:
        for i, note in enumerate(v):
            if not isinstance(note, str) or not note.strip():
                raise ValueError(f"operator_notes[{i}] must be a non-empty string")
        return v

    @model_validator(mode="after")
    def _hours_form_full_day(self) -> "ScenarioRequest":
        hours = [h.hour for h in self.hours]
        if sorted(hours) != list(range(24)):
            raise ValueError("hours must be exactly the 24 unique integers 0..23")
        return self

    def sorted_hours(self) -> list[HourEntry]:
        return sorted(self.hours, key=lambda h: h.hour)


# --- Response models ---

class DirectiveInterpretation(BaseModel):
    note_index: int
    applies: bool
    directive_type: str
    structured_adjustment: Optional[dict[str, Any]]
    explanation: str


class HourlyPlanEntry(BaseModel):
    hour: int
    grid_kwh: float
    solar_used_kwh: float
    battery_action: str
    battery_kwh: float
    battery_energy_after_kwh: float


class OptimizeResponse(BaseModel):
    scenario_id: str
    directive_interpretation: list[DirectiveInterpretation]
    hourly_plan: list[HourlyPlanEntry]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str


# --- LLM Intermediate Representation (Appendix A) ---

class IRWindow(BaseModel):
    model_config = ConfigDict(extra="ignore")
    start_hour: int
    end_hour: int


class IRInterpretation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    note_index: int
    directive_type: str
    windows: list[IRWindow] = Field(default_factory=list)
    factor: Optional[float] = None
    minimum_energy_kwh: Optional[float] = None
    reserve_percent_of_capacity: Optional[float] = None
    max_grid_kwh: Optional[float] = None
    explanation: str = ""


class IRResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    interpretations: list[IRInterpretation]
