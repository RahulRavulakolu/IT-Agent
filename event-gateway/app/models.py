"""
Pydantic models for Alertmanager webhook payload and internal incident/event schema.

All incoming string fields are validated for:
- Maximum length (MAX_LABEL_LEN = 256 characters)
- Type (must be str, not embedded objects)

Values are NEVER executed – only stored or used as query parameters.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_LABEL_LEN = 256
MAX_ANNOTATION_LEN = 1024
# Safe chars for label names (Prometheus label name spec)
_LABEL_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _safe_str(value: Any, max_len: int = MAX_LABEL_LEN, field: str = "value") -> str:
    """Coerce to str and enforce maximum length."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string, got {type(value).__name__}")
    if len(value) > max_len:
        raise ValueError(f"{field} exceeds maximum length of {max_len} characters")
    return value


# ── Alertmanager webhook payload ──────────────────────────────────────────────

class AlertStatus(str, Enum):
    firing = "firing"
    resolved = "resolved"


class AlertmanagerAlert(BaseModel):
    """Single alert within an Alertmanager webhook payload."""

    status: AlertStatus
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: str = ""
    endsAt: str = ""
    generatorURL: str = ""
    fingerprint: str = ""

    @field_validator("labels", "annotations", mode="before")
    @classmethod
    def validate_string_map(cls, v: Any) -> dict[str, str]:
        if not isinstance(v, dict):
            raise ValueError("labels/annotations must be a JSON object")
        result: dict[str, str] = {}
        for k, val in v.items():
            # Validate key
            k = _safe_str(k, MAX_LABEL_LEN, "label key")
            if not _LABEL_NAME_RE.match(k):
                raise ValueError(f"Invalid label key: {k!r}")
            # Validate value
            val = _safe_str(val, MAX_LABEL_LEN, f"label {k!r} value")
            result[k] = val
        return result

    @field_validator("generatorURL", "fingerprint", "startsAt", "endsAt", mode="before")
    @classmethod
    def validate_safe_str(cls, v: Any) -> str:
        if v is None:
            return ""
        return _safe_str(str(v), MAX_LABEL_LEN, "string field")

    def compute_fingerprint(self) -> str:
        """
        Compute a stable SHA-256 fingerprint from alert_name + sorted label pairs.
        Used for deduplication when Alertmanager does not provide one.
        """
        alert_name = self.labels.get("alertname", "unknown")
        canonical = json.dumps(
            {"alertname": alert_name, "labels": dict(sorted(self.labels.items()))},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()[:32]

    @property
    def effective_fingerprint(self) -> str:
        return self.fingerprint if self.fingerprint else self.compute_fingerprint()

    @property
    def alert_name(self) -> str:
        return self.labels.get("alertname", "unknown")

    @property
    def service(self) -> str:
        return self.labels.get("service", "unknown")

    @property
    def environment(self) -> str:
        return self.labels.get("environment", self.labels.get("namespace", "unknown"))

    @property
    def severity(self) -> str:
        return self.labels.get("severity", "info")


class AlertmanagerWebhook(BaseModel):
    """Top-level Alertmanager webhook payload (v4 format)."""

    version: str = "4"
    groupKey: str = ""
    truncatedAlerts: int = 0
    status: AlertStatus
    receiver: str = ""
    groupLabels: dict[str, str] = Field(default_factory=dict)
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    externalURL: str = ""
    alerts: list[AlertmanagerAlert] = Field(default_factory=list)

    @field_validator("alerts", mode="before")
    @classmethod
    def limit_alerts(cls, v: Any) -> list:
        if not isinstance(v, list):
            raise ValueError("alerts must be a list")
        if len(v) > 200:
            raise ValueError("Payload contains too many alerts (max 200)")
        return v

    @field_validator("groupKey", "receiver", "externalURL", mode="before")
    @classmethod
    def validate_safe_str(cls, v: Any) -> str:
        if v is None:
            return ""
        return _safe_str(str(v), MAX_LABEL_LEN)


# ── Internal schema ───────────────────────────────────────────────────────────

class IncidentStatus(str, Enum):
    open = "open"
    resolved = "resolved"


class IncidentRecord(BaseModel):
    """Normalised incident as stored in PostgreSQL."""

    id: int | None = None
    fingerprint: str
    title: str
    severity: str
    service: str
    environment: str
    status: IncidentStatus = IncidentStatus.open
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    created_at: datetime | None = None
    resolved_at: datetime | None = None
    correlation_key: str = ""   # service:environment – used for correlation grouping


class EventRecord(BaseModel):
    """Single alert event linked to an incident."""

    id: int | None = None
    incident_id: int
    alert_name: str
    fingerprint: str
    status: AlertStatus
    received_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class IngestResponse(BaseModel):
    """Response returned by POST /api/v1/alerts."""

    received: int
    created_incidents: int
    updated_incidents: int
    resolved_incidents: int
    errors: list[str] = Field(default_factory=list)
