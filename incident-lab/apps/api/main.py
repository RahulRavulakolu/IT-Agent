"""
api service – FastAPI backend.

Build-time flag BUGGY_BUILD=true produces api:v2-bad which:
  - starts cleanly and passes readiness
  - returns HTTP 500 on ~70% of non-health requests with ~1.5s added latency

Runtime flags:
  LEAK_MODE=on  → steady memory growth (simulates a leak)

Config (from ConfigMap / env vars):
  DATABASE_URL   – postgres DSN, validated at startup
  SERVICE_NAME   – injected name
  DATA_DIR       – mount point for tmpfs (default /data)

Metrics:
  http_requests_total{service,method,endpoint,status}
  http_request_duration_seconds{service,method,endpoint}
  app_data_volume_used_ratio{service}  – statvfs of /data
"""
import asyncio
import logging
import os
import random
import sys
import time
import threading
from pathlib import Path

import psycopg2
from fastapi import FastAPI, Response, Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from pythonjsonlogger import jsonlogger

# ---------------------------------------------------------------------------
# Build-time buggy flag
# ---------------------------------------------------------------------------
BUGGY_BUILD = os.environ.get("BUGGY_BUILD", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Logging – structured JSON
# ---------------------------------------------------------------------------
logger = logging.getLogger("api")
_handler = logging.StreamHandler(sys.stdout)
_formatter = jsonlogger.JsonFormatter(
    fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
_handler.setFormatter(_formatter)
logger.addHandler(_handler)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SERVICE_NAME = os.environ.get("SERVICE_NAME", "api")
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
LEAK_MODE = os.environ.get("LEAK_MODE", "off").lower() == "on"

def validate_config() -> None:
    """Validate required config; exit 1 with ERROR log on failure."""
    errors = []
    if not DATABASE_URL:
        errors.append("DATABASE_URL is required but not set")
    elif not (DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://")):
        errors.append(f"invalid DATABASE_URL: must start with postgresql:// or postgres://, got: {DATABASE_URL!r}")
    if errors:
        for msg in errors:
            logger.error(
                f"ERROR invalid config: {msg}",
                extra={"service": SERVICE_NAME, "error": msg},
            )
        sys.exit(1)

validate_config()
logger.info("Config validated", extra={"service": SERVICE_NAME, "data_dir": str(DATA_DIR), "leak_mode": LEAK_MODE, "buggy": BUGGY_BUILD})

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
DATA_VOLUME_RATIO = Gauge(
    "app_data_volume_used_ratio",
    "Fraction of /data tmpfs used (0..1)",
    ["service"],
)

# ---------------------------------------------------------------------------
# In-memory store (simple, avoids migration complexity for the lab)
# ---------------------------------------------------------------------------
_items: list[dict] = []
_item_id_counter = 0

# Memory leak accumulator
_leak_buckets: list[bytes] = []

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="api", version="1.0.0")


def _update_volume_gauge() -> None:
    """Update the data volume ratio gauge via statvfs."""
    try:
        import os as _os
        st = _os.statvfs(str(DATA_DIR))
        total = st.f_blocks * st.f_frsize
        free = st.f_bfree * st.f_frsize
        used = total - free
        ratio = used / total if total > 0 else 0.0
        DATA_VOLUME_RATIO.labels(service=SERVICE_NAME).set(ratio)
    except Exception as exc:
        logger.warning("statvfs failed", extra={"service": SERVICE_NAME, "error": str(exc)})


def _volume_monitor_thread() -> None:
    """Background thread: update gauge every 5 s."""
    while True:
        _update_volume_gauge()
        time.sleep(5)


def _leak_thread() -> None:
    """Background thread: allocate ~1MB every 2 s when LEAK_MODE=on."""
    while True:
        time.sleep(2)
        _leak_buckets.append(b"X" * (1024 * 1024))
        logger.debug("leak step", extra={"service": SERVICE_NAME, "buckets": len(_leak_buckets)})


def _db_connect() -> psycopg2.extensions.connection | None:
    """Try to connect to Postgres; return None on failure (soft – we use in-memory fallback)."""
    try:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=5)
        conn.autocommit = True
        return conn
    except Exception as exc:
        logger.warning("DB connect failed, using in-memory store", extra={"service": SERVICE_NAME, "error": str(exc)})
        return None


_db_conn: psycopg2.extensions.connection | None = None


@app.on_event("startup")
async def startup() -> None:
    global _db_conn
    # Ensure /data directory structure exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    archive_dir = DATA_DIR / "archive"
    archive_dir.mkdir(exist_ok=True)
    # Pre-seed archive with old log files (safe to delete, used by disk_full remediation)
    for i in range(1, 6):
        old_log = archive_dir / f"audit-2024-0{i:02d}.log"
        if not old_log.exists():
            old_log.write_text(f"# archived audit log month 2024-{i:02d}\n" + "log entry\n" * 50)

    _db_conn = _db_connect()

    # Start background threads
    threading.Thread(target=_volume_monitor_thread, daemon=True).start()
    if LEAK_MODE:
        logger.warning("LEAK_MODE enabled – memory will grow", extra={"service": SERVICE_NAME})
        threading.Thread(target=_leak_thread, daemon=True).start()

    logger.info("Service started", extra={"service": SERVICE_NAME, "buggy": BUGGY_BUILD})


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def metrics_and_fault_middleware(request: Request, call_next):
    path = request.url.path
    is_probe = path in ("/metrics", "/healthz", "/readyz")

    start = time.perf_counter()

    # BUGGY BUILD: inject errors on non-probe paths
    if BUGGY_BUILD and not is_probe:
        if random.random() < 0.70:
            await asyncio.sleep(1.5)  # add latency
            elapsed = time.perf_counter() - start
            REQUEST_COUNT.labels(
                service=SERVICE_NAME, method=request.method, endpoint=path, status="500"
            ).inc()
            REQUEST_LATENCY.labels(
                service=SERVICE_NAME, method=request.method, endpoint=path
            ).observe(elapsed)
            logger.error(
                "Injected error (buggy build)",
                extra={"service": SERVICE_NAME, "path": path},
            )
            return JSONResponse(status_code=500, content={"error": "internal error (buggy build)"})

    response = await call_next(request)
    elapsed = time.perf_counter() - start

    if not is_probe:
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
    # For buggy build: still pass readiness (subtle bug)
    return {"status": "ready", "service": SERVICE_NAME}


# ---------------------------------------------------------------------------
# Prometheus
# ---------------------------------------------------------------------------
@app.get("/metrics")
async def metrics_endpoint():
    _update_volume_gauge()
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# Business endpoints
# ---------------------------------------------------------------------------
@app.get("/status")
async def status():
    return {
        "service": SERVICE_NAME,
        "db": "connected" if _db_conn else "in-memory",
        "items": len(_items),
        "leak_mode": LEAK_MODE,
        "buggy": BUGGY_BUILD,
    }


@app.get("/items")
async def list_items():
    return {"items": _items, "count": len(_items)}


@app.post("/items")
async def create_item(request: Request):
    global _item_id_counter
    body = await request.json()
    name = body.get("name", f"item-{_item_id_counter}")
    _item_id_counter += 1
    item = {"id": _item_id_counter, "name": name}
    _items.append(item)

    # Write audit file to /data (triggers ENOSPC when disk full)
    audit_path = DATA_DIR / f"audit_{_item_id_counter}.log"
    try:
        audit_path.write_text(f"AUDIT item_id={_item_id_counter} name={name}\n")
    except OSError as exc:
        import errno
        if exc.errno == errno.ENOSPC:
            logger.error(
                "No space left on device",
                extra={"service": SERVICE_NAME, "path": str(audit_path), "error": str(exc)},
            )
            return JSONResponse(status_code=507, content={"error": "No space left on device", "errno": 28})
        raise

    return JSONResponse(status_code=201, content=item)


@app.delete("/items/{item_id}")
async def delete_item(item_id: int):
    global _items
    before = len(_items)
    _items = [i for i in _items if i["id"] != item_id]
    if len(_items) == before:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return {"deleted": item_id}
