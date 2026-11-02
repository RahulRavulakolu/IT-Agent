"""
Event Gateway – Phase 1
=======================
Receives Alertmanager webhook payloads, validates and normalises them into
Incidents + Events, deduplicates by fingerprint, correlates related alerts
within a configurable time window, and persists everything to PostgreSQL.

Endpoints
---------
POST /api/v1/alerts          – Alertmanager webhook receiver
GET  /api/v1/incidents       – list active incidents (query params: service, env, status)
GET  /api/v1/incidents/{id}  – single incident with events
GET  /healthz                – liveness probe
GET  /readyz                 – readiness probe (checks DB connectivity)
GET  /metrics                – Prometheus metrics

Security
--------
All incoming alert label / annotation values are treated as untrusted input.
- Field values are validated for length (≤ 256 chars) and safe characters.
- Values are never executed – only stored as JSONB.
- No shell execution of any kind.
"""
import logging
import sys
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pythonjsonlogger import jsonlogger

from app.api.routes import router as api_router
from app.api.health import router as health_router
from app.api.metrics_endpoint import router as metrics_router
from app.db.connection import init_db

# ── Structured logging ────────────────────────────────────────────────────────

log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logger = logging.getLogger("event-gateway")
_handler = logging.StreamHandler(sys.stdout)
_formatter = jsonlogger.JsonFormatter(
    fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
_handler.setFormatter(_formatter)
logger.addHandler(_handler)
logger.setLevel(getattr(logging, log_level, logging.INFO))

# Root logger also structured so uvicorn access logs are captured
logging.root.addHandler(_handler)
logging.root.setLevel(getattr(logging, log_level, logging.INFO))

# ── Application ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="IT-Agent Event Gateway",
    version="1.0.0",
    description="Phase 1: incident detection, event ingestion, correlation, and storage.",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # lab-only; tighten for production
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(health_router)
app.include_router(metrics_router)


@app.on_event("startup")
async def on_startup() -> None:
    logger.info("event-gateway starting up")
    await init_db()
    logger.info("event-gateway ready")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    logger.info("event-gateway shutting down")
