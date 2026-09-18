from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import FastAPI, Request
from pydantic import ValidationError

from app.config import settings
from app.errors import ApiError, error_response, validate_semantics
from app.pipeline import process
from app.schemas import ScenarioRequest

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger("gridwise.api")

app = FastAPI(title="GridWise LLM", version="1.0.0")

MAX_BODY_BYTES = 256 * 1024


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/optimize-energy")
async def optimize_energy(request: Request):
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return error_response(400, "INVALID_REQUEST", "Request body too large")

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return error_response(400, "MALFORMED_JSON", "Request body is not valid JSON")

    try:
        req = ScenarioRequest.model_validate(data)
    except ValidationError:
        return error_response(400, "INVALID_REQUEST", "Request does not match the required schema")

    try:
        validate_semantics(req)
    except ApiError as e:
        return error_response(e.status_code, e.code, e.message)

    request_id = uuid.uuid4().hex[:8]
    try:
        response, meta = await asyncio.to_thread(process, req)
    except ApiError as e:
        logger.info("req=%s scenario=%s error=%s", request_id, req.scenario_id, e.code)
        return error_response(e.status_code, e.code, e.message)
    except Exception:
        logger.exception("req=%s scenario=%s unexpected error", request_id, req.scenario_id)
        return error_response(500, "INTERNAL_ERROR", "An internal error occurred")

    logger.info("req=%s scenario=%s degraded=%s types=%s latency_ms=%s cost=%s",
                request_id, meta["scenario_id"], meta["degraded"],
                meta["directive_types"], meta["latency_ms"], meta["total_cost_bdt"])
    return response


@app.exception_handler(ApiError)
async def _api_error_handler(_request: Request, exc: ApiError):
    return error_response(exc.status_code, exc.code, exc.message)


@app.exception_handler(Exception)
async def _unexpected_handler(_request: Request, _exc: Exception):
    return error_response(500, "INTERNAL_ERROR", "An internal error occurred")
