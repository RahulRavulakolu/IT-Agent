"""
PostgreSQL connection and schema initialisation.

Uses psycopg2 (synchronous, thread-safe).  Wrapped in asyncio.run_in_executor
where needed to avoid blocking the event loop.

All SQL is parameterised – no string interpolation of user data.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import contextmanager
from typing import Generator

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

logger = logging.getLogger("event-gateway.db")

_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://labuser:labpass123@db-service:5432/incidentlab",
)

_conn = None


def _get_connection():
    global _conn
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed. Install psycopg2-binary to connect to PostgreSQL.")
    if _conn is None or _conn.closed:
        logger.info("Opening PostgreSQL connection", extra={"url": _DATABASE_URL.split("@")[-1]})
        _conn = psycopg2.connect(_DATABASE_URL, connect_timeout=10)
        _conn.autocommit = False
    return _conn


@contextmanager
def get_cursor():
    """Context manager yielding a DictCursor. Commits on success, rolls back on error."""
    conn = _get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


async def init_db() -> None:
    """Idempotent schema initialisation. Safe to call on every startup."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_migrations)


def _run_migrations() -> None:
    """Execute DDL migrations synchronously."""
    with get_cursor() as cur:
        # Load and execute the migration SQL
        import pathlib
        migration_file = pathlib.Path(__file__).parent.parent.parent / "migrations" / "001_init.sql"
        if migration_file.exists():
            sql = migration_file.read_text()
            cur.execute(sql)
            logger.info("Schema migrations applied")
        else:
            logger.warning("Migration file not found; applying inline schema")
            _apply_inline_schema(cur)


def _apply_inline_schema(cur) -> None:
    """Inline schema as fallback if migration file is missing."""
    cur.execute("""
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
            resolved_at       TIMESTAMPTZ,
            CONSTRAINT incidents_fingerprint_open_unique
                UNIQUE NULLS NOT DISTINCT (fingerprint, resolved_at)
        );

        CREATE INDEX IF NOT EXISTS incidents_fingerprint_idx
            ON incidents (fingerprint);
        CREATE INDEX IF NOT EXISTS incidents_status_idx
            ON incidents (status);
        CREATE INDEX IF NOT EXISTS incidents_correlation_key_idx
            ON incidents (correlation_key, created_at);

        CREATE TABLE IF NOT EXISTS events (
            id          BIGSERIAL PRIMARY KEY,
            incident_id BIGINT      NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
            alert_name  TEXT        NOT NULL,
            fingerprint TEXT        NOT NULL,
            status      TEXT        NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            payload     JSONB       NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS events_incident_id_idx ON events (incident_id);
        CREATE INDEX IF NOT EXISTS events_fingerprint_idx ON events (fingerprint);
        CREATE INDEX IF NOT EXISTS events_received_at_idx ON events (received_at DESC);
    """)
