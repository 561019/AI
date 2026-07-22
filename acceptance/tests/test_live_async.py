from __future__ import annotations

from uuid import uuid4

from acceptance.lib.envelope import make_envelope
from acceptance.tests.live_base import LiveTestCase


class LiveAsyncTest(LiveTestCase):
    def test_async_receipt_contains_queryable_task(self) -> None:
        envelope = make_envelope(
            actor=self.actor(),
            source_layer="business_application",
            source_module="acceptance-console",
            target_layer="business_engine",
            target_module="engine-gateway",
            capability="intent.analyze",
            action="intent.analyze",
            request_type="execute",
            payload={"utterance": "异步验收：计算七月份销售提成"},
        )
        submitted = self.client.request(
            "POST",
            self.url("application_gateway_url", "/api/v1/application/instructions"),
            envelope,
        )
        self.assertEqual(202, submitted.status)
        self.assert_standard_response(submitted.body)
        self.assertEqual("accepted", submitted.body["status"])
        task_id = submitted.body.get("task_id")
        self.assertTrue(task_id)
        status = self.client.request(
            "GET",
            self.url("application_gateway_url", f"/api/v1/tasks/{task_id}"),
        )
        self.assertEqual(200, status.status)
        self.assertEqual(envelope["trace_id"], status.body.get("trace_id"))
        self.assertIn(
            status.body.get("state"),
            {"accepted", "running", "waiting_dependency", "waiting_human", "succeeded"},
        )

    def test_duplicate_and_out_of_order_callbacks_are_safe(self) -> None:
        callback_url = self.url("engine_gateway_url", "/api/v1/callbacks")
        task_id = str(uuid4())
        trace_id = str(uuid4())
        base = {
            "event_id": str(uuid4()),
            "event_type": "task.progressed",
            "message_id": str(uuid4()),
            "request_id": str(uuid4()),
            "trace_id": trace_id,
            "task_id": task_id,
            "sequence": 2,
            "progress": 50,
            "data": {},
            "occurred_at": "2026-07-21T12:00:00+08:00",
        }
        first = self.client.request("POST", callback_url, base)
        duplicate = self.client.request("POST", callback_url, base)
        self.assertIn(first.status, {204, 404})
        self.assertEqual(first.status, duplicate.status)

        old = dict(base)
        old["event_id"] = str(uuid4())
        old["message_id"] = str(uuid4())
        old["sequence"] = 1
        old["progress"] = 10
        stale = self.client.request("POST", callback_url, old)
        self.assertIn(stale.status, {204, 404, 409})
