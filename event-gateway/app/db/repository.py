"""
Incident repository – all PostgreSQL read/write operations for incidents and events.

All queries use parameterised placeholders (%s).  No user-controlled values
are interpolated into SQL strings.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.db.connection import get_cursor
from app.models import AlertmanagerAlert, AlertStatus, IncidentRecord, IncidentStatus

logger = logging.getLogger("event-gateway.repository")


def upsert_incident(alert: AlertmanagerAlert) -> tuple[IncidentRecord, bool]:
    """
    Find an existing open incident for this fingerprint or create a new one.

    Returns (incident, created) where created=True if a new row was inserted.

    Deduplication logic:
    - An open incident with the same fingerprint is reused.
    - If no open incident exists, a new one is created.
    - Concurrent upserts are safe because of the UNIQUE constraint on
      (fingerprint) where status='open' (enforced by partial unique index).
    """
    fp = alert.effective_fingerprint
    title = _build_title(alert)
    correlation_key = f"{alert.service}:{alert.environment}"

    with get_cursor() as cur:
        # Look for an open incident with this fingerprint
        cur.execute(
            """
            SELECT id, fingerprint, title, severity, service, environment,
                   status, labels, annotations, correlation_key,
                   created_at, resolved_at
            FROM incidents
            WHERE fingerprint = %s AND status = 'open'
            LIMIT 1
            """,
            (fp,),
        )
        row = cur.fetchone()
        if row:
            incident = _row_to_incident(row)
            return incident, False

        # Create new incident
        cur.execute(
            """
            INSERT INTO incidents
                (fingerprint, title, severity, service, environment, status,
                 labels, annotations, correlation_key)
            VALUES (%s, %s, %s, %s, %s, 'open', %s, %s, %s)
            RETURNING id, fingerprint, title, severity, service, environment,
                      status, labels, annotations, correlation_key,
                      created_at, resolved_at
            """,
            (
                fp,
                title,
                alert.severity,
                alert.service,
                alert.environment,
                json.dumps(dict(sorted(alert.labels.items()))),
                json.dumps(dict(sorted(alert.annotations.items()))),
                correlation_key,
            ),
        )
        row = cur.fetchone()
        incident = _row_to_incident(row)
        logger.info(
            "Created incident",
            extra={
                "incident_id": incident.id,
                "fingerprint": fp,
                "alert_name": alert.alert_name,
                "service": alert.service,
            },
        )
        return incident, True


def resolve_incident(alert: AlertmanagerAlert) -> IncidentRecord | None:
    """
    Mark an open incident as resolved.  Returns the updated incident or None
    if no open incident was found.
    """
    fp = alert.effective_fingerprint
    now = datetime.now(tz=timezone.utc)

    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE incidents
            SET status = 'resolved', resolved_at = %s
            WHERE fingerprint = %s AND status = 'open'
            RETURNING id, fingerprint, title, severity, service, environment,
                      status, labels, annotations, correlation_key,
                      created_at, resolved_at
            """,
            (now, fp),
        )
        row = cur.fetchone()
        if row:
            incident = _row_to_incident(row)
            logger.info(
                "Resolved incident",
                extra={"incident_id": incident.id, "fingerprint": fp},
            )
            return incident
    return None


def record_event(incident_id: int, alert: AlertmanagerAlert, raw_payload: dict[str, Any]) -> None:
    """Insert an event row linked to an incident."""
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO events (incident_id, alert_name, fingerprint, status, payload)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                incident_id,
                alert.alert_name,
                alert.effective_fingerprint,
                alert.status.value,
                json.dumps(raw_payload),
            ),
        )


def get_incident_by_id(incident_id: int) -> IncidentRecord | None:
    """Fetch a single incident by primary key."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, fingerprint, title, severity, service, environment,
                   status, labels, annotations, correlation_key,
                   created_at, resolved_at
            FROM incidents WHERE id = %s
            """,
            (incident_id,),
        )
        row = cur.fetchone()
        return _row_to_incident(row) if row else None


def list_incidents(
    service: str | None = None,
    environment: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[IncidentRecord]:
    """List incidents with optional filters."""
    conditions = []
    params: list[Any] = []

    if service:
        conditions.append("service = %s")
        params.append(service)
    if environment:
        conditions.append("environment = %s")
        params.append(environment)
    if status:
        conditions.append("status = %s")
        params.append(status)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    params.extend([limit, offset])

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, fingerprint, title, severity, service, environment,
                   status, labels, annotations, correlation_key,
                   created_at, resolved_at
            FROM incidents
            {where}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            params,
        )
        return [_row_to_incident(r) for r in cur.fetchall()]


def list_events_for_incident(incident_id: int, limit: int = 100) -> list[dict[str, Any]]:
    """Return all events for an incident."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, incident_id, alert_name, fingerprint, status, received_at, payload
            FROM events
            WHERE incident_id = %s
            ORDER BY received_at ASC
            LIMIT %s
            """,
            (incident_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def find_correlated_incidents(
    service: str,
    environment: str,
    window_seconds: int = 300,
) -> list[IncidentRecord]:
    """
    Find open incidents for the same service+environment within the correlation window.
    Used to surface related incidents to the caller (not auto-merged – Phase 2 will do that).
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, fingerprint, title, severity, service, environment,
                   status, labels, annotations, correlation_key,
                   created_at, resolved_at
            FROM incidents
            WHERE correlation_key = %s
              AND status = 'open'
              AND created_at >= NOW() - (%s || ' seconds')::interval
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (f"{service}:{environment}", str(window_seconds)),
        )
        return [_row_to_incident(r) for r in cur.fetchall()]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_title(alert: AlertmanagerAlert) -> str:
    summary = alert.annotations.get("summary", "")
    if summary:
        return summary[:200]
    return f"{alert.alert_name} on {alert.service} ({alert.environment})"


def _row_to_incident(row: Any) -> IncidentRecord:
    labels = row["labels"] if isinstance(row["labels"], dict) else json.loads(row["labels"] or "{}")
    annotations = row["annotations"] if isinstance(row["annotations"], dict) else json.loads(row["annotations"] or "{}")
    return IncidentRecord(
        id=row["id"],
        fingerprint=row["fingerprint"],
        title=row["title"],
        severity=row["severity"],
        service=row["service"],
        environment=row["environment"],
        status=IncidentStatus(row["status"]),
        labels=labels,
        annotations=annotations,
        correlation_key=row.get("correlation_key", ""),
        created_at=row["created_at"],
        resolved_at=row.get("resolved_at"),
    )
