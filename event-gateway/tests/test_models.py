"""
Unit tests for data models, validation, and fingerprint calculation.
Compatible with both pytest and standard library unittest.
"""
import unittest
from pydantic import ValidationError
from app.models import (
    AlertmanagerWebhook,
    AlertmanagerAlert,
    AlertStatus,
    IncidentRecord,
    IncidentStatus,
)


class TestAlertModels(unittest.TestCase):
    def test_valid_alertmanager_webhook(self):
        payload = {
            "version": "4",
            "groupKey": "test-group",
            "status": "firing",
            "receiver": "event-gateway",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "ApiCrashLoopBackOff",
                        "service": "api",
                        "severity": "critical",
                        "namespace": "staging",
                    },
                    "annotations": {
                        "summary": "api containers are restarting repeatedly",
                    },
                    "startsAt": "2026-11-01T12:00:00Z",
                    "fingerprint": "abc123456",
                }
            ],
        }
        model = AlertmanagerWebhook.model_validate(payload)
        self.assertEqual(len(model.alerts), 1)
        alert = model.alerts[0]
        self.assertEqual(alert.status, AlertStatus.firing)
        self.assertEqual(alert.alert_name, "ApiCrashLoopBackOff")
        self.assertEqual(alert.service, "api")
        self.assertEqual(alert.effective_fingerprint, "abc123456")

    def test_fingerprint_generation_deterministic(self):
        alert1 = AlertmanagerAlert.model_validate({
            "status": "firing",
            "labels": {
                "service": "api",
                "alertname": "ApiDataVolumeFull",
                "severity": "warning",
                "environment": "staging",
            },
        })
        alert2 = AlertmanagerAlert.model_validate({
            "status": "firing",
            "labels": {
                "alertname": "ApiDataVolumeFull",
                "environment": "staging",
                "severity": "warning",
                "service": "api",
            },
        })
        # Labels in different insertion order must yield identical effective_fingerprint
        self.assertEqual(alert1.effective_fingerprint, alert2.effective_fingerprint)
        self.assertEqual(len(alert1.effective_fingerprint), 32)

    def test_reject_untrusted_oversized_label_value(self):
        oversized = "A" * 300
        with self.assertRaises(ValidationError):
            AlertmanagerAlert.model_validate({
                "status": "firing",
                "labels": {"alertname": "TestAlert", "bad_label": oversized},
            })

    def test_reject_invalid_label_key(self):
        with self.assertRaises(ValidationError):
            AlertmanagerAlert.model_validate({
                "status": "firing",
                "labels": {"123invalid_key": "val"},
            })

    def test_reject_too_many_alerts(self):
        alerts = [{"status": "firing", "labels": {"alertname": f"A{i}"}} for i in range(250)]
        with self.assertRaises(ValidationError):
            AlertmanagerWebhook.model_validate({
                "status": "firing",
                "alerts": alerts,
            })


if __name__ == "__main__":
    unittest.main()
