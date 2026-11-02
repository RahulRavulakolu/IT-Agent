"""
Health and readiness probes for event-gateway.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Response, status
from app.db.connection import get_cursor

logger = logging.getLogger("event-gateway.health")
router = APIRouter(tags=["health"])


@router.get("/healthz", status_code=status.HTTP_200_OK)
async def healthz():
    """Liveness probe: returns 200 OK if service process is running."""
    return {"status": "ok", "service": "event-gateway"}


@router.get("/readyz")
async def readyz():
    """
    Readiness probe: verifies database connectivity and schema availability.
    Returns 200 if connected, 503 if database check fails.
    """
    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1 FROM incidents LIMIT 1;")
            _ = cur.fetchone()
        return {"status": "ready", "database": "connected"}
    except Exception as exc:
        logger.warning("Readiness probe failed DB check: %s", exc)
        return Response(
            content='{"status": "not ready", "error": "database unreachable"}',
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            media_type="application/json",
        )
