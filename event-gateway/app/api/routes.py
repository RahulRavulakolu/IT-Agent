"""
Alertmanager webhook receiver and incident query endpoints.

POST /api/v1/alerts
    Accepts an Alertmanager v4 webhook payload. For each alert:
    - Validates and sanitises all label/annotation values (untrusted input)
    - Deduplicates by fingerprint (SHA-256 of alertname + sorted labels)
    - Creates or updates an incident in PostgreSQL
    - Records every alert event regardless of deduplication
    - Correlates with other open incidents for the same service+environment

GET  /api/v1/incidents
GET  /api/v1/incidents/{id}
    Read-only queries for incident state.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram

from app.db import repository
from app.models import (
    AlertStatus,
    AlertmanagerWebhook,
    IngestResponse,
    IncidentRecord,
)

logger = logging.getLogger("event-gateway.routes")
router = APIRouter(prefix="/api/v1")

CORRELATION_WINDOW = int(os.environ.get("CORRELATION_WINDOW_SECONDS", "300"))

# ── Prometheus counters ───────────────────────────────────────────────────────

_ALERTS_RECEIVED = Counter(
    "gateway_alerts_received_total",
    "Total Alertmanager alerts received",
    ["status"],
)
_INCIDENTS_CREATED = Counter(
    "gateway_incidents_created_total",
    "Incidents created",
    ["severity", "service"],
)
_INCIDENTS_RESOLVED = Counter(
    "gateway_incidents_resolved_total",
    "Incidents resolved",
    ["service"],
)
_INGEST_ERRORS = Counter(
    "gateway_ingest_errors_total",
    "Errors during alert ingestion",
)
_INGEST_DURATION = Histogram(
    "gateway_ingest_duration_seconds",
    "Time to process a full webhook payload",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)


# ── Webhook receiver ──────────────────────────────────────────────────────────

@router.post("/alerts", response_model=IngestResponse, status_code=200)
async def receive_alerts(request: Request) -> IngestResponse:
    """
    Alertmanager webhook receiver.

    Validates the payload against the AlertmanagerWebhook schema (Pydantic),
    then processes each alert synchronously (psycopg2 is not async-native).
    """
    start = datetime.now(tz=timezone.utc)

    # Parse and validate
    try:
        raw_body = await request.json()
    except Exception as exc:
        logger.warning("Failed to parse JSON payload", extra={"error": str(exc)})
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

    try:
        payload = AlertmanagerWebhook.model_validate(raw_body)
    except Exception as exc:
        logger.warning("Payload validation failed", extra={"error": str(exc)})
        raise HTTPException(status_code=422, detail=f"Validation error: {exc}")

    logger.info(
        "Webhook received",
        extra={
            "status": payload.status,
            "alert_count": len(payload.alerts),
            "receiver": payload.receiver,
        },
    )

    # Process alerts (run in thread pool to keep event loop free)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        _process_payload,
        payload,
        raw_body,
    )

    elapsed = (datetime.now(tz=timezone.utc) - start).total_seconds()
    _INGEST_DURATION.observe(elapsed)

    return result


def _process_payload(payload: AlertmanagerWebhook, raw_body: dict[str, Any]) -> IngestResponse:
    """Synchronous processing of a full Alertmanager webhook payload."""
    created = 0
    updated = 0
    resolved = 0
    errors: list[str] = []

    for alert in payload.alerts:
        _ALERTS_RECEIVED.labels(status=alert.status.value).inc()
        try:
            if alert.status == AlertStatus.firing:
                incident, is_new = repository.upsert_incident(alert)
                # Record the raw event regardless of dedup
                raw_alert = {
                    "status": alert.status.value,
                    "labels": alert.labels,
                    "annotations": alert.annotations,
                    "startsAt": alert.startsAt,
                    "fingerprint": alert.effective_fingerprint,
                }
                repository.record_event(incident.id, alert, raw_alert)

                if is_new:
                    created += 1
                    _INCIDENTS_CREATED.labels(
                        severity=alert.severity, service=alert.service
                    ).inc()
                    # Log correlated incidents for observability
                    correlated = repository.find_correlated_incidents(
                        alert.service,
                        alert.environment,
                        CORRELATION_WINDOW,
                    )
                    if len(correlated) > 1:
                        logger.warning(
                            "New incident has correlated open incidents",
                            extra={
                                "incident_id": incident.id,
                                "correlated_ids": [i.id for i in correlated],
                                "service": alert.service,
                                "environment": alert.environment,
                            },
                        )
                else:
                    updated += 1
                    logger.debug(
                        "Alert deduplicated to existing incident",
                        extra={"incident_id": incident.id, "fingerprint": alert.effective_fingerprint},
                    )

            elif alert.status == AlertStatus.resolved:
                inc = repository.resolve_incident(alert)
                if inc:
                    resolved += 1
                    _INCIDENTS_RESOLVED.labels(service=alert.service).inc()
                    raw_alert = {
                        "status": alert.status.value,
                        "labels": alert.labels,
                        "annotations": alert.annotations,
                        "endsAt": alert.endsAt,
                        "fingerprint": alert.effective_fingerprint,
                    }
                    repository.record_event(inc.id, alert, raw_alert)

        except Exception as exc:
            _INGEST_ERRORS.inc()
            msg = f"Error processing alert {alert.alert_name!r}: {exc}"
            logger.error(msg, extra={"fingerprint": alert.effective_fingerprint})
            errors.append(msg)

    return IngestResponse(
        received=len(payload.alerts),
        created_incidents=created,
        updated_incidents=updated,
        resolved_incidents=resolved,
        errors=errors,
    )


# ── Incident queries ──────────────────────────────────────────────────────────

@router.get("/incidents", response_model=list[dict])
async def list_incidents(
    service: str | None = Query(None, max_length=64),
    environment: str | None = Query(None, max_length=64),
    status: str | None = Query(None, pattern="^(open|resolved)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    """List incidents with optional filters."""
    loop = asyncio.get_event_loop()
    incidents = await loop.run_in_executor(
        None,
        repository.list_incidents,
        service,
        environment,
        status,
        limit,
        offset,
    )
    return [_incident_to_dict(i) for i in incidents]


@router.get("/incidents/{incident_id}", response_model=dict)
async def get_incident(incident_id: int) -> dict:
    """Get a single incident with its event history."""
    loop = asyncio.get_event_loop()
    incident = await loop.run_in_executor(
        None, repository.get_incident_by_id, incident_id
    )
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    events = await loop.run_in_executor(
        None, repository.list_events_for_incident, incident_id
    )

    result = _incident_to_dict(incident)
    result["events"] = [
        {
            "id": e["id"],
            "alert_name": e["alert_name"],
            "status": e["status"],
            "received_at": e["received_at"].isoformat() if e["received_at"] else None,
        }
        for e in events
    ]
    return result


def _incident_to_dict(incident: IncidentRecord) -> dict:
    return {
        "id": incident.id,
        "fingerprint": incident.fingerprint,
        "title": incident.title,
        "severity": incident.severity,
        "service": incident.service,
        "environment": incident.environment,
        "status": incident.status.value,
        "labels": incident.labels,
        "created_at": incident.created_at.isoformat() if incident.created_at else None,
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
    }
