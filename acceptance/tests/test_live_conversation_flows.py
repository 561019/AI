from __future__ import annotations

import time

from acceptance.lib.envelope import make_envelope
from acceptance.tests.live_base import LiveTestCase


class LiveConversationFlowsTest(LiveTestCase):
    def _waiting_task(self, utterance: str = "计算七月份两笔销售业绩合计") -> tuple[dict, dict]:
        envelope = make_envelope(
            actor=self.actor(), source_layer="business_application", source_module="chat-validation",
            target_layer="business_engine", target_module="engine-gateway",
            capability="intent.analyze", action="intent.analyze", request_type="execute",
            payload={"utterance": utterance},
        )
        submitted = self.client.request("POST", self.url("application_gateway_url", "/api/v1/application/instructions"), envelope)
        task_id = submitted.body["task_id"]
        for _ in range(30):
            task = self.client.request("GET", self.url("application_gateway_url", f"/api/v1/tasks/{task_id}"))
            if task.body.get("state") == "waiting_human": return envelope, task.body
            time.sleep(.1)
        self.fail("task did not reach waiting_human")

    def test_human_reject_stops_before_permission(self) -> None:
        envelope, task = self._waiting_task()
        confirmation = task["confirmation_ref"]["id"]
        result = self.client.request("POST", self.url("application_gateway_url", f"/api/v1/confirmations/{confirmation}/decisions"), {"decision": "reject", "actor": self.actor()})
        self.assertEqual(200, result.status)
        trace = self.client.request("GET", self.url("application_gateway_url", f"/api/v1/traces/{envelope['trace_id']}/calls"))
        targets = {item["target_module"] for item in trace.body["items"]}
        self.assertIn("model-dispatcher", targets)
        self.assertNotIn("permission-adapter", targets)
        self.assertNotIn("rule-adapter", targets)

    def test_permission_deny_stops_before_rule(self) -> None:
        envelope, task = self._waiting_task()
        confirmation = task["confirmation_ref"]["id"]
        result = self.client.request("POST", self.url("application_gateway_url", f"/api/v1/confirmations/{confirmation}/decisions"), {"decision": "confirm", "actor": self.actor(), "simulate_permission_denied": True})
        self.assertEqual(502, result.status)
        trace = self.client.request("GET", self.url("application_gateway_url", f"/api/v1/traces/{envelope['trace_id']}/calls"))
        targets = {item["target_module"] for item in trace.body["items"]}
        self.assertIn("permission-adapter", targets)
        self.assertNotIn("rule-adapter", targets)

    def test_confirm_uses_values_returned_by_intent_engine(self) -> None:
        _, task = self._waiting_task("计算两笔销售业绩合计：5000 + 2680.5")
        intent = task["result_ref"]["data"]["tasks"][0]
        self.assertEqual([5000, 2680.5], intent["parameters"]["values"])
        confirmation = task["confirmation_ref"]["id"]
        result = self.client.request(
            "POST",
            self.url("application_gateway_url", f"/api/v1/confirmations/{confirmation}/decisions"),
            {"decision": "confirm", "actor": self.actor()},
        )
        self.assertEqual(200, result.status)
        self.assertEqual("rule.calculate", result.body["data"]["selected_capability"])
        self.assertEqual(7680.5, result.body["data"]["capability_result"]["value"])

    def test_unregistered_intent_capability_is_not_faked(self) -> None:
        envelope = make_envelope(
            actor=self.actor(), source_layer="business_application", source_module="application-gateway",
            target_layer="business_engine", target_module="workflow-execution",
            capability="workflow.execute", action="workflow.execute", request_type="execute",
            payload={
                "execution_kind": "intent_driven", "platform_task_id": "dynamic-test-task",
                "intent_task": {"capability_code": "knowledge.answer", "description": "回答制度问题", "parameters": {}},
            },
        )
        result = self.client.request("POST", self.url("workflow_engine_url", "/api/v1/workflows/executions"), envelope)
        self.assertEqual(422, result.status)
        self.assertEqual("CAPABILITY_NOT_REGISTERED", result.body["error"]["code"])
