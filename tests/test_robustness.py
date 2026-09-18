"""Never-crash / stability / secret-safety (§4.9)."""
from __future__ import annotations

import app.main as main_module
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_repeated_requests_stable(valid_request):
    results = [client.post("/optimize-energy", json=valid_request) for _ in range(20)]
    assert all(r.status_code == 200 for r in results)
    # deterministic: identical output across repeats
    bodies = {r.text for r in results}
    assert len(bodies) == 1


def test_degraded_mode_still_200(valid_request):
    # no provider keys in tests -> rule fallback path -> must still succeed
    valid_request["operator_notes"] = ["Some totally unparseable free text about nothing."]
    r = client.post("/optimize-energy", json=valid_request)
    assert r.status_code == 200
    assert r.json()["directive_interpretation"][0]["directive_type"] == "no_op"


def test_no_secret_in_response(valid_request):
    r = client.post("/optimize-energy", json=valid_request)
    assert "gsk_" not in r.text
    assert "Traceback" not in r.text


def test_unexpected_error_returns_controlled_500(valid_request, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaboom secret gsk_XXXX")

    monkeypatch.setattr(main_module, "process", boom)
    r = client.post("/optimize-energy", json=valid_request)
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "gsk_" not in r.text and "kaboom" not in r.text


def test_all_directive_types_end_to_end(valid_request):
    # fallback handles these phrasings; ensures the wired plan obeys each
    valid_request["operator_notes"] = [
        "Do not charge the battery between 2 AM and 5 AM.",
        "Keep at least 90 kWh in the battery from 6 PM until 9 PM.",
        "Grid import must not exceed 150 kWh from 7 PM until 9 PM.",
    ]
    r = client.post("/optimize-energy", json=valid_request)
    assert r.status_code == 200
    types = [e["directive_type"] for e in r.json()["directive_interpretation"]]
    assert types == ["no_charge_window", "minimum_battery_reserve", "max_grid_window"]
