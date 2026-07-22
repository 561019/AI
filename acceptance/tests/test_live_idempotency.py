from __future__ import annotations

from uuid import uuid4

from acceptance.lib.envelope import make_envelope
from acceptance.tests.live_base import LiveTestCase


class LiveIdempotencyTest(LiveTestCase):
    def test_same_key_same_body_reuses_result_and_changed_body_conflicts(self) -> None:
        key = f"acceptance-idempotency-{uuid4()}"
        envelope = make_envelope(
            actor=self.actor(),
            source_layer="business_application",
            source_module="acceptance-console",
            target_layer="business_engine",
            target_module="engine-gateway",
            capability="intent.analyze",
            action="intent.analyze",
            request_type="execute",
            payload={"utterance": "幂等测试：计算七月份销售提成"},
            idempotency_key=key,
        )
        url = self.url("application_gateway_url", "/api/v1/application/instructions")
        first = self.client.request("POST", url, envelope)
        second = self.client.request("POST", url, envelope)
        self.assertIn(first.status, {200, 202})
        self.assertEqual(first.status, second.status)
        self.assertEqual(first.body.get("task_id"), second.body.get("task_id"))

        changed = dict(envelope)
        changed["message_id"] = str(uuid4())
        changed["payload"] = {"utterance": "幂等测试：改成八月份销售提成"}
        conflict = self.client.request("POST", url, changed)
        self.assertEqual(409, conflict.status)
        error = (conflict.body or {}).get("error") or {}
        self.assertEqual("IDEMPOTENCY_CONFLICT", error.get("code"))
