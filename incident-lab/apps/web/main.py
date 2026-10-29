"""
web service – FastAPI frontend that proxies requests to api.
Emits structured JSON logs, exposes /healthz, /readyz, /metrics.
Reads config from environment (injected via ConfigMap).
"""
import logging
import os
import sys
import time

import httpx
from fastapi import FastAPI, Response, Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pythonjsonlogger import jsonlogger

# ---------------------------------------------------------------------------
# Logging – structured JSON
# ---------------------------------------------------------------------------
logger = logging.getLogger("web")
handler = logging.StreamHandler(sys.stdout)
formatter = jsonlogger.JsonFormatter(
    fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------
API_URL = os.environ.get("API_URL", "")
SERVICE_NAME = os.environ.get("SERVICE_NAME", "web")

if not API_URL:
    logger.error("ERROR invalid config: API_URL is required but not set",
                 extra={"service": SERVICE_NAME, "error": "missing API_URL"})
    sys.exit(1)

logger.info("Config loaded", extra={"service": SERVICE_NAME, "api_url": API_URL})

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["service", "method", "endpoint", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["service", "method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="web", version="1.0.0")

# Shared httpx client (connection-pooled)
_http_client: httpx.AsyncClient | None = None


@app.on_event("startup")
async def startup() -> None:
    global _http_client
    _http_client = httpx.AsyncClient(base_url=API_URL, timeout=10.0)
    logger.info("Service started", extra={"service": SERVICE_NAME})


@app.on_event("shutdown")
async def shutdown() -> None:
    if _http_client:
        await _http_client.aclose()


# ---------------------------------------------------------------------------
# Middleware: record every request
# ---------------------------------------------------------------------------
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    path = request.url.path
    # Don't record /metrics and /healthz to avoid noise
    if path not in ("/metrics", "/healthz", "/readyz"):
        REQUEST_COUNT.labels(
            service=SERVICE_NAME,
            method=request.method,
            endpoint=path,
            status=str(response.status_code),
        ).inc()
        REQUEST_LATENCY.labels(
            service=SERVICE_NAME,
            method=request.method,
            endpoint=path,
        ).observe(elapsed)
        logger.info(
            "request",
            extra={
                "service": SERVICE_NAME,
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "duration_s": round(elapsed, 4),
            },
        )
    return response


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------
@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/readyz")
async def readyz():
    # _http_client is set in startup; if not yet ready, report not-ready
    if _http_client is None:
        return Response(status_code=503, content="starting")
    try:
        r = await _http_client.get("/healthz")
        r.raise_for_status()
    except Exception as exc:
        logger.warning("Readiness probe: api unreachable", extra={"service": SERVICE_NAME, "error": str(exc)})
        return Response(status_code=503, content="api not ready")
    return {"status": "ready", "service": SERVICE_NAME}


# ---------------------------------------------------------------------------
# Prometheus metrics endpoint
# ---------------------------------------------------------------------------
@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# Proxy endpoints
# ---------------------------------------------------------------------------
@app.get("/")
async def index():
    return {"service": SERVICE_NAME, "message": "Incident Lab – web frontend"}


@app.get("/items")
async def list_items():
    """Proxy GET /items to api."""
    try:
        r = await _http_client.get("/items")
        return JSONResponse(status_code=r.status_code, content=r.json())
    except Exception as exc:
        logger.error("upstream error", extra={"service": SERVICE_NAME, "error": str(exc)})
        return JSONResponse(status_code=502, content={"error": "upstream unavailable"})


@app.post("/items")
async def create_item(request: Request):
    """Proxy POST /items to api."""
    try:
        body = await request.json()
        r = await _http_client.post("/items", json=body)
        return JSONResponse(status_code=r.status_code, content=r.json())
    except Exception as exc:
        logger.error("upstream error", extra={"service": SERVICE_NAME, "error": str(exc)})
        return JSONResponse(status_code=502, content={"error": "upstream unavailable"})


@app.get("/status")
async def status():
    """Return api status (used by load generator health checks)."""
    try:
        r = await _http_client.get("/status")
        return JSONResponse(status_code=r.status_code, content=r.json())
    except Exception as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})
