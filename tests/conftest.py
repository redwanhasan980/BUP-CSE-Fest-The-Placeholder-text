import copy

import pytest

from app.config import settings
from app.interpreter import clear_cache


@pytest.fixture(autouse=True)
def _offline_llm():
    """Keep the whole test suite offline: no provider keys -> interpret() falls
    back to the deterministic rule parser. Tests that pass explicit mock
    providers are unaffected."""
    primary, secondary = settings.llm_primary_api_key, settings.llm_secondary_api_key
    settings.llm_primary_api_key = ""
    settings.llm_secondary_api_key = ""
    clear_cache()
    yield
    settings.llm_primary_api_key = primary
    settings.llm_secondary_api_key = secondary
    clear_cache()


def _valid_request() -> dict:
    hours = [
        {"hour": h, "demand_kwh": 100, "solar_kwh": 0, "tariff_bdt_per_kwh": 10}
        for h in range(24)
    ]
    return {
        "scenario_id": "TEST-01",
        "operator_notes": ["The cafeteria menu changes tomorrow."],
        "hours": hours,
        "battery": {
            "capacity_kwh": 200,
            "initial_energy_kwh": 100,
            "minimum_energy_kwh": 40,
            "max_charge_kwh_per_hour": 50,
            "max_discharge_kwh_per_hour": 50,
        },
    }


@pytest.fixture
def valid_request():
    return copy.deepcopy(_valid_request())


@pytest.fixture
def make_request():
    def _factory(**overrides):
        req = copy.deepcopy(_valid_request())
        req.update(overrides)
        return req

    return _factory
