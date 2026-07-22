from __future__ import annotations

from acceptance.tests.live_base import LiveTestCase


class LiveHealthTest(LiveTestCase):
    def test_required_services_are_healthy(self) -> None:
        services = {
            "application_gateway_url": "/health",
            "engine_gateway_url": "/health",
            "foundation_gateway_url": "/health",
            "intent_engine_url": "/health",
            "delivered_intent_engine_url": "/health",
            "workflow_engine_url": "/health",
            "delivered_workflow_engine_url": "/health",
            "rule_engine_url": "/health",
            "delivered_rule_engine_url": "/health",
            "content_engine_url": "/health",
            "delivered_content_engine_url": "/health",
            "permission_service_url": "/health",
            "model_dispatcher_url": "/health",
            "template_management_url": "/health",
        }
        failures: list[str] = []
        for key, path in services.items():
            result = self.client.request("GET", self.url(key, path))
            if result.status != 200:
                failures.append(f"{key}={result.status}")
        self.assertEqual([], failures)
