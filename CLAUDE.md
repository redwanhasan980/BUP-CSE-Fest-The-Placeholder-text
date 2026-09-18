# CLAUDE.md — GridWise LLM

Project rules for AI collaborators. Read `IMPLEMENTATION_PLAN.md` (build order + test catalogue) and `SRS.md` (design). The **Problem Statement PDF is canonical** and overrides the Participant Guide on any conflict.

## What this is
HTTP API (`GET /health`, `POST /optimize-energy`) that interprets 1–3 operator notes with an LLM → typed directives → deterministic guardrails → 24h LP (SciPy HiGHS) → replay-verified min-cost plan. BUP CSE Fest 2026 hackathon submission.

## Hard rules
- **Exact contract.** Endpoint paths, JSON field names, and enums must match the Problem Statement byte-for-byte. No trailing-slash redirects, no path prefix.
- **Correctness before cost.** The judge replays the plan against the *true* directive. A plan that ignores a correctly-read directive scores 0 for that case. Never sacrifice validity to lower cost.
- **LLM only reads notes.** Never send demand/solar/tariff/battery numbers to the LLM except `capacity_kwh`, and use that only in deterministic code (percent→kWh). The LLM must never invent demand/tariff/battery changes or unsupported directive types.
- **LLM output is untrusted** until guardrails pass. `no_op` is the only directive with `applies=false` + `structured_adjustment=null`; every other type is `applies=true` + exact key set.
- **factor = usable fraction remaining.** "80% reduction" → 0.2, "drop to 20%" → 0.2. #1 trap.
- **Time windows are start-inclusive, end-exclusive**, hours unique ints 0–23 ascending. Midnight-as-end = 24.
- **Totals recomputed from the rounded `hourly_plan`**, never from solver internals. 4-dp rounding, clamp tiny negatives, tolerance 0.01.
- **Never crash / never 5xx on valid input.** 400 = structural, 422 = semantically impossible, 500 = controlled internal (generic message, no stack trace/secrets).

## Secrets
- `.env` is git-ignored — never commit it, never print the key in code/logs/responses/README.
- Only `.env.example` (names, no values) is committed.
- Do not bake secrets into the Docker image.

## Git
- **Do not `git add`, `commit`, or `push`** unless explicitly asked. Keep `.gitignore` current.

## Testing
- Deterministic tests (validation, optimizer, verifier, normalizer, guardrails) must pass **offline, no network**.
- Prove 10/10 public cases match reference cost within 0.01 before trusting the optimizer.
- Cover the corner cases in `IMPLEMENTATION_PLAN.md` §4; add new adversarial cases as found.

## Style
- Python 3.11, FastAPI, Pydantic v2. Keep modules small and unit-testable. Minimal comments (only non-obvious WHY). Be concise; conserve tokens.
