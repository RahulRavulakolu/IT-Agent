"""
Unit tests for API route logic and deduplication / correlation flows.
Compatible with both pytest and standard library unittest.
"""
import unittest
from unittest.mock import MagicMock, patch

try:
    from app.api.routes import _process_payload
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

from app.models import AlertmanagerWebhook, IncidentRecord, IncidentStatus


class TestRoutesAndDedup(unittest.TestCase):

    @unittest.skipUnless(HAS_DEPS, "fastapi or prometheus_client not installed in this environment")
    def test_process_payload_deduplication(self):
        webhook_data = {
            "version": "4",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "ApiOOMKilled", "service": "api", "severity": "critical"},
                    "fingerprint": "fp-oom-1",
                },
                {
                    "status": "firing",
                    "labels": {"alertname": "ApiOOMKilled", "service": "api", "severity": "critical"},
                    "fingerprint": "fp-oom-1",
                },
            ],
        }
        payload = AlertmanagerWebhook.model_validate(webhook_data)

        dummy_incident = IncidentRecord(
            id=101,
            fingerprint="fp-oom-1",
            title="api OOMKilled",
            severity="critical",
            service="api",
            environment="staging",
            status=IncidentStatus.open,
        )

        with patch("app.db.repository.upsert_incident") as mock_upsert, \
             patch("app.db.repository.record_event") as mock_record_event, \
             patch("app.db.repository.find_correlated_incidents") as mock_correlated:

            mock_upsert.side_effect = [(dummy_incident, True), (dummy_incident, False)]
            mock_correlated.return_value = [dummy_incident]

            resp = _process_payload(payload, webhook_data)

            self.assertEqual(resp.received, 2)
            self.assertEqual(resp.created_incidents, 1)
            self.assertEqual(resp.updated_incidents, 1)
            self.assertEqual(resp.resolved_incidents, 0)
            self.assertEqual(mock_record_event.call_count, 2)

    @unittest.skipUnless(HAS_DEPS, "fastapi or prometheus_client not installed in this environment")
    def test_process_payload_resolution(self):
        webhook_data = {
            "version": "4",
            "status": "resolved",
            "alerts": [
                {
                    "status": "resolved",
                    "labels": {"alertname": "WebServiceDown", "service": "web", "severity": "critical"},
                    "fingerprint": "fp-web-down",
                }
            ],
        }
        payload = AlertmanagerWebhook.model_validate(webhook_data)

        dummy_incident = IncidentRecord(
            id=102,
            fingerprint="fp-web-down",
            title="web service down",
            severity="critical",
            service="web",
            environment="staging",
            status=IncidentStatus.resolved,
        )

        with patch("app.db.repository.resolve_incident") as mock_resolve, \
             patch("app.db.repository.record_event") as mock_record_event:
            mock_resolve.return_value = dummy_incident

            resp = _process_payload(payload, webhook_data)

            self.assertEqual(resp.received, 1)
            self.assertEqual(resp.created_incidents, 0)
            self.assertEqual(resp.updated_incidents, 0)
            self.assertEqual(resp.resolved_incidents, 1)
            self.assertEqual(mock_record_event.call_count, 1)


if __name__ == "__main__":
    unittest.main()
