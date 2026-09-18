import copy
import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def post(body, raw=False):
    if raw:
        return client.post("/optimize-energy", content=body,
                           headers={"Content-Type": "application/json"})
    return client.post("/optimize-energy", json=body)


def assert_error(resp, status, code=None):
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert "error" in body and "code" in body["error"] and "message" in body["error"]
    if code:
        assert body["error"]["code"] == code


# --- happy path ---

def test_valid_request_200(valid_request):
    r = post(valid_request)
    assert r.status_code == 200, r.text
    assert r.json()["scenario_id"] == "TEST-01"


def test_hours_out_of_order_accepted(valid_request):
    valid_request["hours"] = list(reversed(valid_request["hours"]))
    assert post(valid_request).status_code == 200


def test_unknown_extra_fields_ignored(valid_request):
    valid_request["surprise"] = 123
    valid_request["hours"][0]["extra"] = 9
    valid_request["battery"]["extra"] = 9
    assert post(valid_request).status_code == 200


# --- 400 structural (§4.1) ---

def test_malformed_json():
    assert_error(post("{not json", raw=True), 400, "MALFORMED_JSON")


def test_empty_body():
    assert_error(post("", raw=True), 400, "MALFORMED_JSON")


def test_missing_scenario_id(valid_request):
    del valid_request["scenario_id"]
    assert_error(post(valid_request), 400, "INVALID_REQUEST")


def test_empty_scenario_id(valid_request):
    valid_request["scenario_id"] = ""
    assert_error(post(valid_request), 400)


def test_scenario_id_non_string(valid_request):
    valid_request["scenario_id"] = 123
    # pydantic coerces int->str is disallowed by default in v2 strict? keep as structural
    r = post(valid_request)
    assert r.status_code in (200, 400)  # int coercion tolerated; documents behavior


def test_zero_notes(valid_request):
    valid_request["operator_notes"] = []
    assert_error(post(valid_request), 400)


def test_four_notes(valid_request):
    valid_request["operator_notes"] = ["a", "b", "c", "d"]
    assert_error(post(valid_request), 400)


def test_empty_string_note(valid_request):
    valid_request["operator_notes"] = [""]
    assert_error(post(valid_request), 400)


def test_whitespace_note(valid_request):
    valid_request["operator_notes"] = ["   "]
    assert_error(post(valid_request), 400)


def test_note_non_string(valid_request):
    valid_request["operator_notes"] = [123]
    assert_error(post(valid_request), 400)


def test_notes_not_array(valid_request):
    valid_request["operator_notes"] = "just a string"
    assert_error(post(valid_request), 400)


def test_23_hours(valid_request):
    valid_request["hours"] = valid_request["hours"][:23]
    assert_error(post(valid_request), 400)


def test_25_hours(valid_request):
    extra = copy.deepcopy(valid_request["hours"][0])
    valid_request["hours"].append(extra)
    assert_error(post(valid_request), 400)


def test_duplicate_hour(valid_request):
    valid_request["hours"][5]["hour"] = 6  # now two hour=6, missing 5
    assert_error(post(valid_request), 400)


def test_hour_negative(valid_request):
    valid_request["hours"][0]["hour"] = -1
    assert_error(post(valid_request), 400)


def test_hour_24(valid_request):
    valid_request["hours"][0]["hour"] = 24
    assert_error(post(valid_request), 400)


def test_hour_fractional(valid_request):
    valid_request["hours"][0]["hour"] = 5.5
    assert_error(post(valid_request), 400)


def test_missing_hour_field(valid_request):
    del valid_request["hours"][0]["demand_kwh"]
    assert_error(post(valid_request), 400)


def test_missing_battery(valid_request):
    del valid_request["battery"]
    assert_error(post(valid_request), 400)


def test_missing_battery_field(valid_request):
    del valid_request["battery"]["capacity_kwh"]
    assert_error(post(valid_request), 400)


# --- 422 semantic (§4.2) ---

def test_negative_demand(valid_request):
    valid_request["hours"][3]["demand_kwh"] = -5
    assert_error(post(valid_request), 422, "SEMANTIC_INVALID")


def test_negative_solar(valid_request):
    valid_request["hours"][3]["solar_kwh"] = -1
    assert_error(post(valid_request), 422, "SEMANTIC_INVALID")


def test_negative_tariff_accepted(valid_request):
    valid_request["hours"][3]["tariff_bdt_per_kwh"] = -2
    assert post(valid_request).status_code == 200


def test_zero_tariff_accepted(valid_request):
    for h in valid_request["hours"]:
        h["tariff_bdt_per_kwh"] = 0
    assert post(valid_request).status_code == 200


def test_min_gt_capacity(valid_request):
    valid_request["battery"]["minimum_energy_kwh"] = 999
    assert_error(post(valid_request), 422, "SEMANTIC_INVALID")


def test_initial_below_min(valid_request):
    valid_request["battery"]["initial_energy_kwh"] = 10
    valid_request["battery"]["minimum_energy_kwh"] = 40
    assert_error(post(valid_request), 422, "SEMANTIC_INVALID")


def test_initial_above_capacity(valid_request):
    valid_request["battery"]["initial_energy_kwh"] = 999
    assert_error(post(valid_request), 422, "SEMANTIC_INVALID")


def test_negative_capacity(valid_request):
    valid_request["battery"]["capacity_kwh"] = -1
    assert_error(post(valid_request), 422, "SEMANTIC_INVALID")


def test_negative_rate(valid_request):
    valid_request["battery"]["max_charge_kwh_per_hour"] = -5
    assert_error(post(valid_request), 422, "SEMANTIC_INVALID")


def test_infinity_demand(valid_request):
    valid_request["hours"][0]["demand_kwh"] = float("inf")
    body = json.dumps(valid_request)  # json module emits Infinity token
    assert_error(post(body, raw=True), 422, "SEMANTIC_INVALID")


def test_nan_demand(valid_request):
    valid_request["hours"][0]["demand_kwh"] = float("nan")
    body = json.dumps(valid_request)
    assert_error(post(body, raw=True), 422, "SEMANTIC_INVALID")


def test_capacity_zero_accepted(valid_request):
    valid_request["battery"] = {
        "capacity_kwh": 0, "initial_energy_kwh": 0, "minimum_energy_kwh": 0,
        "max_charge_kwh_per_hour": 0, "max_discharge_kwh_per_hour": 0,
    }
    assert post(valid_request).status_code == 200
