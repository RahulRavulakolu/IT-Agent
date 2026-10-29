"""
Load generator for incident-lab.
Sends a steady mix of read (GET /items) and write (POST /items) requests
to the web service at ~5 req/s total with 2 simulated users.
"""
import random
from locust import HttpUser, task, between


class LabUser(HttpUser):
    # 0.4 to 0.6 s wait between tasks → ~2.5 req/s per user; with 2 users ≈ 5/s
    wait_time = between(0.4, 0.6)

    @task(3)
    def list_items(self):
        """Read – 3 parts of traffic"""
        with self.client.get("/items", catch_response=True) as resp:
            if resp.status_code >= 500:
                resp.failure(f"5xx: {resp.status_code}")

    @task(1)
    def create_item(self):
        """Write – 1 part of traffic (triggers audit file write on api)"""
        name = f"item-{random.randint(1000, 9999)}"
        with self.client.post(
            "/items",
            json={"name": name},
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 201, 507):
                resp.failure(f"unexpected status: {resp.status_code}")

    @task(1)
    def health(self):
        """Lightweight health check traffic"""
        self.client.get("/healthz")
