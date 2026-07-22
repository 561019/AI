from __future__ import annotations

from acceptance.lib.envelope import make_envelope
from acceptance.tests.live_base import LiveTestCase


class LivePermissionTest(LiveTestCase):
    def _check(self, resource_id: str) -> object:
        envelope = make_envelope(
            actor=self.actor(),
            source_layer="business_engine",
            source_module="workflow-execution",
            target_layer="foundation",
            target_module="foundation-gateway",
            capability="permissions.check",
            action="data.read",
            request_type="query",
            payload={
                "resource": {
                    "type": "data",
                    "id": resource_id,
                    "tenant_id": self.actor()["tenant_id"],
                }
            },
        )
        return self.client.request(
            "POST",
            self.url("foundation_gateway_url", "/api/v1/foundation/instructions"),
            envelope,
        )

    def test_allowed_resource_returns_explicit_decision(self) -> None:
        resource_id = self.config["test_resources"]["allowed_data_id"]
        result = self._check(resource_id)
        self.assertEqual(200, result.status)
        self.assert_standard_response(result.body)
        self.assertEqual("success", result.body["status"])
        self.assertEqual("allow", result.body["data"]["decision"])
        self.assertTrue(result.body["data"].get("decision_id"))

    def test_denied_resource_never_defaults_to_allow(self) -> None:
        resource_id = self.config["test_resources"]["denied_data_id"]
        result = self._check(resource_id)
        self.assertIn(result.status, {200, 403})
        body = result.body
        if isinstance(body, dict) and body.get("status") == "success":
            self.assertEqual("deny", body["data"]["decision"])
        else:
            self.assertNotEqual("allow", (body or {}).get("data", {}).get("decision"))
