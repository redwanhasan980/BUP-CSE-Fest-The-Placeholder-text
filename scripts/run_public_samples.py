"""End-to-end harness against a running service.

Usage:
  python scripts/run_public_samples.py --base-url http://localhost:8000
Compares directive interpretation + independently replays hourly_plan +
checks recalculated cost against the reference (tolerance 0.01).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data" / "public_sample_cases.json"
TOL = 0.01


def load_cases():
    with open(DATA, encoding="utf-8") as f:
        return json.load(f)["cases"]


def replay(inp, resp):
    """Independent replay of hourly_plan; returns list of violation strings."""
    hours = sorted(inp["hours"], key=lambda h: h["hour"])
    demand = [h["demand_kwh"] for h in hours]
    tariff = [h["tariff_bdt_per_kwh"] for h in hours]
    solar = [h["solar_kwh"] for h in hours]
    b = inp["battery"]

    # effective params from the RETURNED interpretation
    eff_solar = list(solar)
    emin = [b["minimum_energy_kwh"]] * 24
    cmax = [b["max_charge_kwh_per_hour"]] * 24
    dmax = [b["max_discharge_kwh_per_hour"]] * 24
    gmax = [None] * 24
    for e in resp["directive_interpretation"]:
        if not e["applies"]:
            continue
        sa = e["structured_adjustment"] or {}
        for h in sa.get("hours", []):
            t = e["directive_type"]
            if t == "solar_reduction":
                eff_solar[h] *= sa["factor"]
            elif t == "minimum_battery_reserve":
                emin[h] = max(emin[h], sa["minimum_energy_kwh"])
            elif t == "no_charge_window":
                cmax[h] = 0
            elif t == "no_discharge_window":
                dmax[h] = 0
            elif t == "max_grid_window":
                gmax[h] = sa["max_grid_kwh"] if gmax[h] is None else min(gmax[h], sa["max_grid_kwh"])

    v = []
    plan = sorted(resp["hourly_plan"], key=lambda x: x["hour"])
    if [p["hour"] for p in plan] != list(range(24)):
        return ["hours not 0..23"]
    prev = b["initial_energy_kwh"]
    for h, p in enumerate(plan):
        ch = p["battery_kwh"] if p["battery_action"] == "charge" else 0
        di = p["battery_kwh"] if p["battery_action"] == "discharge" else 0
        if abs(p["grid_kwh"] + p["solar_used_kwh"] + di - demand[h] - ch) > TOL:
            v.append(f"h{h} balance")
        if p["solar_used_kwh"] > eff_solar[h] + TOL:
            v.append(f"h{h} solar overuse")
        if abs(p["battery_energy_after_kwh"] - (prev + ch - di)) > TOL:
            v.append(f"h{h} transition")
        if p["battery_energy_after_kwh"] < emin[h] - TOL or p["battery_energy_after_kwh"] > b["capacity_kwh"] + TOL:
            v.append(f"h{h} bounds")
        if ch > cmax[h] + TOL or di > dmax[h] + TOL:
            v.append(f"h{h} rate")
        if gmax[h] is not None and p["grid_kwh"] > gmax[h] + TOL:
            v.append(f"h{h} grid cap")
        prev = p["battery_energy_after_kwh"]
    if abs(prev - b["initial_energy_kwh"]) > TOL:
        v.append("neutrality")
    return v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    args = ap.parse_args()

    cases = load_cases()
    passed = 0
    print(f"{'CASE':<12}{'INTERP':<8}{'PLAN':<7}{'COST team/ref':<26}{'ms'}")
    with httpx.Client(timeout=35) as c:
        for case in cases:
            inp = case["input"]
            exp = case["expected_output"]
            import time
            t0 = time.time()
            r = c.post(f"{args.base_url}/optimize-energy", json=inp)
            ms = round((time.time() - t0) * 1000)
            if r.status_code != 200:
                print(f"{case['id']:<12}HTTP {r.status_code}")
                continue
            resp = r.json()

            interp_ok = True
            for got, e in zip(resp["directive_interpretation"], exp["directive_interpretation"]):
                if got["directive_type"] != e["directive_type"] or got["applies"] != e["applies"]:
                    interp_ok = False
                if e["directive_type"] != "no_op":
                    g, ex = got.get("structured_adjustment") or {}, e["structured_adjustment"]
                    if g.get("hours") != ex.get("hours"):
                        interp_ok = False

            viol = replay(inp, resp)
            plan_ok = not viol
            cost_ok = abs(resp["total_cost_bdt"] - exp["total_cost_bdt"]) <= TOL
            if interp_ok and plan_ok and cost_ok:
                passed += 1
            costs = f"{resp['total_cost_bdt']:.2f}/{exp['total_cost_bdt']:.2f}"
            print(f"{case['id']:<12}{'PASS' if interp_ok else 'FAIL':<8}"
                  f"{'PASS' if plan_ok else 'FAIL':<7}{costs:<26}{ms}"
                  + ("" if plan_ok else f"  {viol[:3]}"))

    print(f"\nSummary: {passed}/{len(cases)} passed")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
