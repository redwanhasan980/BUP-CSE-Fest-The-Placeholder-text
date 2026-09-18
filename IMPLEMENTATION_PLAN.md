# GridWise LLM — Implementation Plan

> Companion to `SRS.md` (design) and `README.md` (submission doc). This file is the **actionable build order + test corner-case catalogue**. It does not repeat the SRS; it references it.

Status legend: ⬜ not started · 🟨 in progress · ✅ done

---

## 0. Guiding principles (from the rubric)

The judge scores a **pipeline**, and correctness beats cost. Ranked priority (PG §11):

1. Exact API & JSON contract (endpoints, field names, status codes) — *cheap points, lose them and everything downstream is worthless.*
2. LLM operator-note interpretation (25 pts).
3. Deterministic guardrails.
4. Directive application & energy correctness (25 pts) — **a plan that ignores a correctly-read directive scores zero for that case.**
5. Optimization quality (10 pts) — only counted *after* the case is valid.
6. Reliability, deployment, Docker.
7. Docs & reproducibility.

**Two independent scores per case:** interpretation is graded against ground truth, AND the plan is replayed against the *true* directive (not our reported one). So we must get both right, independently.

Build **deterministic core first** (schemas → optimizer → verifier → tests). It is high-value, needs no LLM, and de-risks the hardest scoring category. LLM interpretation layers on top.

---

## 1. Tech stack (locked)

| Concern | Choice | Note |
|---|---|---|
| Language | Python 3.11 | |
| Web | FastAPI + Uvicorn | ASGI, async routes |
| Validation | Pydantic v2 | strict models; unknown fields ignored |
| Solver | SciPy `linprog(method="highs")` | exact LP |
| LLM SDK | `openai` (OpenAI-compatible) | points at Groq |
| Primary LLM | Groq `openai/gpt-oss-120b` | key already in `.env` |
| Secondary LLM | Cerebras / other OpenAI-compatible | **user will provide a second key** — two-provider failover chain wired |
| Container | `python:3.11-slim`, bind `0.0.0.0:${PORT}` | |

---

## 2. Build order (phases)

### Phase A — Scaffold & health (target: green /health first) ⬜
- `requirements.txt`, `.gitignore` (must include `.env`), `.dockerignore`, `.env.example`
- `app/config.py` — env settings via Pydantic Settings
- `app/main.py` — FastAPI app, `GET /health` → `{"status":"ok"}` (no LLM dependency)
- `Dockerfile`
- **Exit:** `uvicorn app.main:app` serves `/health` 200; `docker build` + run works.

### Phase B — Schemas & request validation ⬜
- `app/schemas.py` — request models (`ScenarioRequest`, `HourEntry`, `Battery`), response models, IR models (Appendix A), `structured_adjustment` per-type models.
- Validation rules → 400 vs 422 split (SRS §4.2, A-01).
- Custom exception handlers for the safe error envelope `{"error":{"code","message"}}`.
- Hour-set validation (exactly {0..23}, unique), notes count 1–3 non-empty, sort hours.
- **Exit:** all request-validation unit tests pass (see §4.1).

### Phase C — Optimizer + plan builder + verifier (the deterministic heart) ⬜
- `app/optimizer.py` — build & solve LP (SRS §7). Variables `g,s,c,d,E` × 24. ε-penalty. Directive → effective-parameter application. Infeasibility handling (recovery ladder §9.2).
- `app/plan.py` (plan builder) — net action → charge/discharge/idle, 4-dp rounding, clamp tiny negatives, **recompute energy chain and totals from rounded plan** (FR-OUT-02/03).
- `app/verifier.py` — replay all V-01..V-12 (SRS §8.2), tol 0.01.
- `app/summary.py` — deterministic `plan_summary`.
- **Exit:** all 10 public cases reproduce reference cost within 0.01 using **ground-truth directives** (bypass LLM); verifier passes on all; corrupted-plan tests all caught (see §4.3, §4.4).

### Phase D — LLM interpretation + normalizer + guardrails ⬜
- `app/llm/prompt.py` — system prompt: directive catalogue, time/percent normalization rules (SRS §6), relevance/no_op rules, **synthetic** few-shot paraphrases (never public wording/numbers). Requests IR (windows + percent, not hour lists).
- `app/llm/client.py` — OpenAI-compatible client, provider chain, per-attempt timeout, `temperature=0`, JSON-schema response format (fallback to json_object + Pydantic).
- `app/normalizer.py` — expand windows → hour lists (end-exclusive, wrap midnight, dedupe, sort); percent-of-capacity → kWh; derive `applies`.
- `app/guardrails.py` — G-01..G-10 (SRS §8.1). Typed pass/fail with reasons.
- `app/interpreter.py` — orchestrate LLM → normalize → guardrails → repair(1) → failover → rule fallback; in-memory LRU cache keyed by `sha256(notes + capacity)`.
- `app/llm/rule_fallback.py` — degraded regex parser (last resort only; unknown → no_op, never invents).
- **Exit:** 10/10 public interpretations match; paraphrase suite ≥95%; robustness tests pass (see §4.5, §4.6).

### Phase E — Wire end-to-end + deadline + logging ⬜
- `POST /optimize-energy` full pipeline; request deadline (25 s) → skip remaining LLM attempts, use fallback.
- LP runs in worker thread (don't block event loop).
- One structured log line per request (no secrets).
- `scripts/run_public_samples.py --base-url` end-to-end harness.
- **Exit:** end-to-end 10/10; p95 ≤ 5 s locally.

### Phase F — Deploy, Docker push, README finalize, video ⬜
- Push image with exact tag+digest; deploy public URL; external curl test; fill README placeholders.

---

## 3. Key implementation decisions (calling out the subtle ones)

1. **400 vs 422** (A-01): structural/type/shape/count/hour-set errors → **400**; well-formed but impossible values (negative energy, min>capacity, initial out of range, NaN/∞, infeasible base scenario) → **422**.
2. **Overlapping same-type directives** (A-03): solar factors **multiply**; reserves take **max**; grid caps take **min**.
3. **Reserve below base minimum** (A-10): effective min = `max(base_min, directive)`. Always valid.
4. **kW vs kWh** (A-05): 1-hour steps ⇒ X kW cap = X kWh/hour.
5. **`no_op` semantics**: the ONLY directive with `applies=false` and `structured_adjustment=null`. Everything else `applies=true` + exact key set.
6. **factor = usable fraction remaining.** "80% reduction" → 0.2. "drop to 20%" → 0.2. Different wording, same value — this is the #1 trap.
7. **LLM gets notes only** — never demand/solar/tariff/battery numbers except `capacity_kwh`, and that is used **only by deterministic code** to convert percentages.
8. **Totals recomputed from the rounded plan**, never from solver internals (judge does the same).
9. **ε-penalty (1e-6)** prevents simultaneous charge+discharge so each hour maps to one clean action.

---

## 4. Test strategy — the corner-case catalogue

> The contest tests hidden cases with heavy paraphrasing and adversarial inputs. Tests below are grouped by module. Deterministic tests are the safety net; interpretation tests are the differentiator. **Every deterministic test must pass offline (no network).**
>
> **Deliverable:** each bucket below becomes a real `tests/test_*.py` file with one assertion per bullet (parametrized where possible). Interpretation buckets (§4.5–§4.7) run against a mock LLM offline AND a small live-LLM subset. The catalogue is a living list — add every new corner case discovered while building.

### 4.1 Request validation → HTTP 400 (structural)
- [ ] Body is not JSON / empty body → 400 `MALFORMED_JSON`.
- [ ] Missing `scenario_id`; `scenario_id` empty string; `scenario_id` non-string → 400.
- [ ] `operator_notes` missing; **0 notes**; **4 notes**; element is empty string; element is whitespace-only (`"   "`); element non-string; `operator_notes` not an array → 400.
- [ ] `hours` has **23** entries; **25** entries; **duplicate** hour (two `hour:5`); `hour:-1`; `hour:24`; hour non-integer (`5.5`, `"5"`); missing `hour`/`demand_kwh`/`solar_kwh`/`tariff_bdt_per_kwh` in any entry → 400.
- [ ] `hours` present but not 24 unique forming exactly {0..23} (e.g. 0..22 plus a duplicate) → 400.
- [ ] `hours` **out of order** (23..0) → **accepted**, sorted internally.
- [ ] Unknown extra top-level / hour / battery fields → **ignored**, 200.
- [ ] `battery` missing entirely or missing any sub-field → 400.

### 4.2 Semantic validation → HTTP 422
- [ ] `demand_kwh` negative; `solar_kwh` negative; capacity/rates negative → 422 `SEMANTIC_INVALID`.
- [ ] `NaN` / `Infinity` / `-Infinity` in any numeric (via `1e999`, or literal if parser allows) → 422 (or 400 if unparseable).
- [ ] `minimum_energy_kwh > capacity_kwh` → 422.
- [ ] `initial_energy_kwh < minimum_energy_kwh` or `> capacity_kwh` → 422.
- [ ] **Negative tariff** → **accepted** (A-08), LP stays bounded.
- [ ] **Zero tariff** hours → accepted.
- [ ] `capacity_kwh == 0` (battery unusable) → accepted; plan must be all-grid, neutrality trivially holds.
- [ ] Base scenario infeasible even with no directives → 422 `INFEASIBLE_SCENARIO` (defensive; guaranteed not to happen for judge cases).

### 4.3 Optimizer (ground-truth directives, no LLM)
- [ ] **All 10 public cases** reproduce reference `total_cost_bdt`, `total_grid_kwh`, `peak_grid_kwh` within 0.01.
- [ ] No hour has simultaneous charge>0 and discharge>0.
- [ ] End energy `E[23] == initial` exactly (within tol) in every case.
- [ ] Zero-solar-all-day scenario solves.
- [ ] Solar > demand+charge headroom ⇒ curtailment (solar_used < effective solar) allowed, no export.
- [ ] Tight reserve near capacity solves and respects reserve every listed hour.
- [ ] Grid cap tighter than demand ⇒ forces solar/battery to cover the gap; if cap makes an hour infeasible on the base scenario the ladder handles it.
- [ ] Negative-tariff hour ⇒ optimizer charges to the rate limit if useful.
- [ ] Overlapping directives: two solar_reductions on same hour ⇒ factors multiply; two reserves ⇒ max; two grid caps ⇒ min.

### 4.4 Verifier (deliberately corrupted plans — every corruption MUST be caught)
- [ ] 24-entry / hour-set corruption (23 entries, dup hour, hour 24).
- [ ] Energy-balance off by 0.02 in one hour → caught.
- [ ] `solar_used > effective_solar` (esp. in a solar_reduction hour) → caught.
- [ ] Battery `E_after` below active reserve; above capacity → caught.
- [ ] `battery_kwh` exceeds max_charge / max_discharge → caught.
- [ ] Charge in a `no_charge_window` hour; discharge in a `no_discharge_window` hour → caught.
- [ ] `grid_kwh > max_grid_kwh` in a capped hour → caught.
- [ ] `battery_action=idle` but `battery_kwh != 0` → caught.
- [ ] `E_after[23] != initial` → caught.
- [ ] Reported `total_cost_bdt`/`total_grid_kwh`/`peak_grid_kwh` disagree with plan → caught.
- [ ] Values within 0.01 tolerance → **not** falsely flagged.

### 4.5 Interpretation — directive types & values (mock LLM + live)
For each: correct `directive_type`, `applies`, `hours`, numeric value, exact `structured_adjustment` shape.
- [ ] **solar_reduction**: "drop to 20%" → 0.2; "80% reduction"/"reduced by 80%"/"loses 80%" → 0.2; "half"/"50% output" → 0.5; "roughly a quarter"/"25%" → 0.25; "one-fifth" → 0.2; "no solar"/"panels offline"/"zero output" → 0.0; factor exactly 0 and exactly 1.
- [ ] **minimum_battery_reserve**: absolute "at least 90 kWh" → 90; "no less than 90 kWh"; "above 90 kWh" (≥, A-06); percent "50% of capacity"/"half-charged" → 0.5×capacity computed in code; reserve below base min (still applies, max taken).
- [ ] **no_charge_window**: "do not charge", "charger isolated", "charging disabled/circuit off".
- [ ] **no_discharge_window**: "must not discharge", "discharge disabled", "don't draw from the battery".
- [ ] **max_grid_window**: "must not exceed 155 kWh", "capped at", "limited to", "at or below"; "155 kW limit" → 155 kWh (A-05).

### 4.6 Interpretation — time normalization (end-exclusive everywhere)
- [ ] "1 PM to 3 PM"/"between 1 and 3 PM"/"13:00–15:00" → [13,14].
- [ ] "noon until 2 PM" → [12,13]; "midday".
- [ ] "10 PM until midnight" → [22,23] (midnight-as-end = 24).
- [ ] Single hour: "at 7 PM"/"during the 18:00 hour" → [19].
- [ ] "3 hours from 6 PM" → [18,19,20].
- [ ] "after 9 PM"/"from 9 PM onward" → [21,22,23]; "before 6 AM"/"until 6 AM" → [0..5].
- [ ] "all day"/"whole day" → [0..23].
- [ ] Crossing midnight "10 PM to 2 AM" → [0,1,22,23] (wrap+sort).
- [ ] Multiple windows "1–2 AM and 4–5 AM" → [1,4].
- [ ] Missing AM/PM with solar context "panel washing from one until three" → [13,14] (daylight).

### 4.7 Interpretation — relevance / no_op (distractors)
- [ ] Unrelated: cafeteria, library, registration, club notice, room booking, seminar → no_op.
- [ ] Different period: "next week", "next month", "last week", "yesterday" → no_op.
- [ ] Cancellation/negation: "the 2–4 PM maintenance has been cancelled" → no_op.
- [ ] Energy-related but unsupported (demand spike, tariff change, general statement) → **no_op, never invent** demand/tariff/battery change.
- [ ] "tomorrow" in an energy note → **applies** (the scenario IS the next 24h, A-02).
- [ ] Mixed: 3 notes, some relevant some not, correct per-index mapping.
- [ ] All-relevant (3 directives) and all-no_op scenarios.

### 4.8 Guardrails (LLM output treated as untrusted)
- [ ] LLM returns non-JSON / schema mismatch → repair → failover.
- [ ] `directive_type` outside the 6 → rejected, never silently mapped.
- [ ] Wrong entry count / missing `note_index` / duplicate index / out-of-range index → repair/failover.
- [ ] Non-`no_op` with empty `hours` → repair.
- [ ] `factor` = 20 (percentage-as-error, not 0.2) → repair, not silently guessed; `factor` = 1.5 or negative → repair.
- [ ] reserve > capacity or negative → repair/failover.
- [ ] `max_grid_kwh` negative or non-finite → repair/failover.
- [ ] LLM attempts to change demand/solar/tariff/battery → field dropped (IR schema forbids it).
- [ ] `no_op` with non-null adjustment, or non-`no_op` with null → normalized deterministically.

### 4.9 Robustness / reliability (never crash, never 5xx on valid input)
- [ ] Simulated LLM outage (bad key / timeout) → degraded rule fallback → 200.
- [ ] LLM returns garbage repeatedly → note becomes no_op with explanation, 200.
- [ ] Repeated identical request → cache hit, identical output.
- [ ] 50 sequential + 10 concurrent requests → 0 failures, p95 ≤ 5 s.
- [ ] Request deadline reached mid-LLM → skip to fallback, still 200.
- [ ] Oversized body (>256 KB) → rejected safely.
- [ ] No secret/API key/stack trace ever appears in any response or log (assert in tests).

### 4.10 Paraphrase robustness suite
- [ ] ≥30 synthetic paraphrases across all 6 directive types (different numbers/hours than public cases) → ≥95% exact directive+hours+value match. These are our own generated cases, not public wording.

---

## 5. Repo layout to create

```
app/{main,config,schemas,interpreter,normalizer,guardrails,optimizer,plan,verifier,summary}.py
app/llm/{client,prompt,rule_fallback}.py
tests/data/public_sample_cases.json        # copy from Documents/
tests/{test_validation,test_optimizer,test_verifier,test_normalizer,test_guardrails,test_interpretation,test_robustness,test_paraphrase}.py
scripts/run_public_samples.py
examples/sample-01.request.json
Dockerfile  .dockerignore  .gitignore  .env.example  requirements.txt
```

---

## 6. Open questions for you (won't block me — I have defaults)

1. ~~Secondary LLM provider~~ **RESOLVED (2026-09-18):** user will supply a second OpenAI-compatible key (e.g. Cerebras). Wire the primary→secondary→rule-fallback chain. Need from you: the key + its `BASE_URL` and `MODEL` id before Phase D.
2. **Deployment target** — Render, Railway, Fly.io, or your own VPS? Affects the Dockerfile/keep-warm details only. *Default: write platform-agnostic Docker; pick host at Phase F.*
3. **Is this the live 4-hour round right now, or prep?** Changes how aggressively I parallelize vs. explain. *Default: build as if for submission, explain as I go.*
4. **`.env` safety** — I will add `.gitignore` with `.env` immediately so the committed key never lands in git history. Confirm the key in `.env` is a throwaway/rotatable one.

---

## 7. Immediate next actions

1. Phase A scaffold (requirements, .gitignore, config, main, /health, Dockerfile).
2. Phase B schemas + validation + tests.
3. Phase C optimizer + verifier + **prove 10/10 cost match offline** — this is the single most important milestone.

I'll proceed top-down unless you redirect.
