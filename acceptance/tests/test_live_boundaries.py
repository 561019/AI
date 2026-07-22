from __future__ import annotations

from acceptance.lib.envelope import make_envelope
from acceptance.tests.live_base import LiveTestCase


class LiveBoundaryTest(LiveTestCase):
    def test_application_cannot_call_foundation_directly(self) -> None:
        envelope = make_envelope(
            actor=self.actor(),
            source_layer="business_application",
            source_module="acceptance-console",
            target_layer="foundation",
            target_module="foundation-gateway",
            capability="data.read",
            action="data.read",
            request_type="query",
            payload={"resource_id": "boundary-test"},
        )
        result = self.client.request(
            "POST",
            self.url("foundation_gateway_url", "/api/v1/foundation/instructions"),
            envelope,
        )
        self.assertIn(result.status, {401, 403})

    def test_unregistered_source_is_rejected(self) -> None:
        envelope = make_envelope(
            actor=self.actor(),
            source_layer="business_engine",
            source_module="unregistered-acceptance-module",
            target_layer="foundation",
            target_module="foundation-gateway",
            capability="data.read",
            action="data.read",
            request_type="query",
            payload={"resource_id": "boundary-test"},
        )
        result = self.client.request(
            "POST",
            self.url("foundation_gateway_url", "/api/v1/foundation/instructions"),
            envelope,
        )
        self.assertIn(result.status, {401, 403})
