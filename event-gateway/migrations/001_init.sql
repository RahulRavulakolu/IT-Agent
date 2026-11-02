-- Phase 1: Event Gateway Database Schema
-- Idempotent schema initialization for PostgreSQL 16+

CREATE TABLE IF NOT EXISTS incidents (
    id                BIGSERIAL PRIMARY KEY,
    fingerprint       TEXT        NOT NULL,
    title             TEXT        NOT NULL,
    severity          TEXT        NOT NULL DEFAULT 'info',
    service           TEXT        NOT NULL DEFAULT 'unknown',
    environment       TEXT        NOT NULL DEFAULT 'unknown',
    status            TEXT        NOT NULL DEFAULT 'open',
    labels            JSONB       NOT NULL DEFAULT '{}',
    annotations       JSONB       NOT NULL DEFAULT '{}',
    correlation_key   TEXT        NOT NULL DEFAULT '',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at       TIMESTAMPTZ
);

-- Partial unique index to enforce that only one OPEN incident exists per fingerprint.
-- Resolved incidents with the same fingerprint can coexist historically.
CREATE UNIQUE INDEX IF NOT EXISTS incidents_fingerprint_open_idx
    ON incidents (fingerprint)
    WHERE status = 'open';

CREATE INDEX IF NOT EXISTS incidents_fingerprint_idx
    ON incidents (fingerprint);

CREATE INDEX IF NOT EXISTS incidents_status_idx
    ON incidents (status);

CREATE INDEX IF NOT EXISTS incidents_correlation_key_idx
    ON incidents (correlation_key, created_at DESC);

CREATE INDEX IF NOT EXISTS incidents_service_env_idx
    ON incidents (service, environment, created_at DESC);

CREATE TABLE IF NOT EXISTS events (
    id          BIGSERIAL PRIMARY KEY,
    incident_id BIGINT      NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    alert_name  TEXT        NOT NULL,
    fingerprint TEXT        NOT NULL,
    status      TEXT        NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload     JSONB       NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS events_incident_id_idx
    ON events (incident_id);

CREATE INDEX IF NOT EXISTS events_fingerprint_idx
    ON events (fingerprint);

CREATE INDEX IF NOT EXISTS events_received_at_idx
    ON events (received_at DESC);
