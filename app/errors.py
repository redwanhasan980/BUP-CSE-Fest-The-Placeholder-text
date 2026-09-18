from __future__ import annotations

import math

from fastapi.responses import JSONResponse

from app.schemas import ScenarioRequest


class ApiError(Exception):
    """Controlled error carrying an HTTP status, machine code, and safe message."""

    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def _finite(x: float) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def validate_semantics(req: ScenarioRequest) -> None:
    """Well-formed but impossible values -> HTTP 422 SEMANTIC_INVALID.

    Tariff may be negative (accepted); everything else must be finite and,
    where it represents energy/rate, non-negative.
    """
    for h in req.hours:
        if not _finite(h.demand_kwh) or h.demand_kwh < 0:
            raise ApiError(422, "SEMANTIC_INVALID", f"demand_kwh at hour {h.hour} must be finite and >= 0")
        if not _finite(h.solar_kwh) or h.solar_kwh < 0:
            raise ApiError(422, "SEMANTIC_INVALID", f"solar_kwh at hour {h.hour} must be finite and >= 0")
        if not _finite(h.tariff_bdt_per_kwh):
            raise ApiError(422, "SEMANTIC_INVALID", f"tariff at hour {h.hour} must be finite")

    b = req.battery
    for name, val in (
        ("capacity_kwh", b.capacity_kwh),
        ("initial_energy_kwh", b.initial_energy_kwh),
        ("minimum_energy_kwh", b.minimum_energy_kwh),
        ("max_charge_kwh_per_hour", b.max_charge_kwh_per_hour),
        ("max_discharge_kwh_per_hour", b.max_discharge_kwh_per_hour),
    ):
        if not _finite(val):
            raise ApiError(422, "SEMANTIC_INVALID", f"battery.{name} must be finite")

    if b.capacity_kwh < 0:
        raise ApiError(422, "SEMANTIC_INVALID", "battery.capacity_kwh must be >= 0")
    if b.max_charge_kwh_per_hour < 0 or b.max_discharge_kwh_per_hour < 0:
        raise ApiError(422, "SEMANTIC_INVALID", "battery charge/discharge rates must be >= 0")
    if b.minimum_energy_kwh < 0 or b.minimum_energy_kwh > b.capacity_kwh:
        raise ApiError(422, "SEMANTIC_INVALID", "battery.minimum_energy_kwh must satisfy 0 <= min <= capacity")
    if not (b.minimum_energy_kwh <= b.initial_energy_kwh <= b.capacity_kwh):
        raise ApiError(422, "SEMANTIC_INVALID", "battery.initial_energy_kwh must satisfy min <= initial <= capacity")
