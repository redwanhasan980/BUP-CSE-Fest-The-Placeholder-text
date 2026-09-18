# Build Progress & Recovery

> Resume point if the machine restarts. Update the checkboxes + "Resume here" after each phase.

**Resume here:** Phase F — deploy to a public host, push Docker image (tag+digest), external curl test, fill README placeholders (URL, image, video, team). Code is complete + fully tested.

Milestones hit: A–E DONE. 177 tests pass offline (`pytest -q`). LIVE end-to-end 10/10 over HTTP with Groq LLM: start server then `.venv\Scripts\python.exe scripts\run_public_samples.py --base-url http://127.0.0.1:8000`. Latencies 108–1186 ms. Still want 2nd provider key from user for failover.

Run server: `.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000`

## Recovery quickstart
```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -q                 # see which phase's tests pass
uvicorn app.main:app --reload
```
Then read the phase table below; the first unchecked phase is where to continue.

## Phase status
- [x] **A** Scaffold & /health — requirements.txt, .dockerignore, app/config.py, app/main.py, Dockerfile — DONE (test_health passes)
- [x] **B** Schemas & validation — app/schemas.py, app/errors.py, error envelope, POST stub — DONE (35 validation tests pass)
- [x] **C** Optimizer + verifier — app/{directives,optimizer,plan,verifier,summary,engine}.py — DONE (**10/10 public cost match offline**; 98 tests pass)
- [x] **D** LLM + normalizer + guardrails — app/{normalizer,guardrails,interpreter}.py, app/llm/{prompt,client,rule_fallback}.py — DONE (offline mocks + live Groq smoke test pass)
- [x] **E** Wire end-to-end — app/pipeline.py, POST wired, deadline, LP in worker thread, logging, scripts/run_public_samples.py — DONE (live 10/10 over HTTP)
- [~] **F** Deploy/Docker/README/video — LOCAL parts DONE (examples/sample-01.request.json, README model-id/SRS-link fixes). EXTERNAL parts need user:
    - [ ] Deploy to a public host (pick Render/Railway/Fly/VPS)
    - [ ] `docker build` + push to Docker Hub/GHCR with exact tag+digest (Docker NOT installed locally)
    - [ ] Fill README placeholders: live URL, image ref+digest, video link, team names
    - [ ] Record ≤3-min video; external curl test from outside network
    - [ ] Rotate the Groq key before making the repo public

## Notes / decisions
- Test corpus lives in tests/data/public_sample_cases.json (copied from Documents/).
- Need from user before Phase D: 2nd provider key + BASE_URL + MODEL.
- Do NOT git commit/push. .env is git-ignored.
