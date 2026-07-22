from __future__ import annotations

import time

from acceptance.lib.config import load_scenario
from acceptance.lib.envelope import make_envelope
from acceptance.tests.live_base import LiveTestCase


class LiveEndToEndTest(LiveTestCase):
    def test_sales_commission_reaches_intent_confirmation(self) -> None:
        scenario = load_scenario("sales_commission.json")
        envelope = make_envelope(
            actor=self.actor(),
            source_layer="business_application",
            source_module="acceptance-console",
            target_layer="business_engine",
            target_module="engine-gateway",
            capability="intent.analyze",
            action="intent.analyze",
            request_type="execute",
            payload={"utterance": scenario["utterance"]},
        )
        submitted = self.client.request(
            "POST",
            self.url("application_gateway_url", "/api/v1/application/instructions"),
            envelope,
        )
        self.assertEqual(202, submitted.status)
        task_id = submitted.body.get("task_id")
        self.assertTrue(task_id)

        deadline = time.monotonic() + min(float(self.config.get("timeout_seconds", 10)), 30)
        latest = None
        while time.monotonic() < deadline:
            latest = self.client.request(
                "GET",
                self.url("application_gateway_url", f"/api/v1/tasks/{task_id}"),
            )
            if latest.status == 200 and latest.body.get("state") in {
                "waiting_human",
                "failed",
                "succeeded",
            }:
                break
            time.sleep(0.25)

        self.assertIsNotNone(latest)
        self.assertEqual(200, latest.status)
        self.assertEqual(envelope["trace_id"], latest.body.get("trace_id"))
        self.assertEqual("waiting_human", latest.body.get("state"))
        confirmation = latest.body.get("confirmation_ref")
        self.assertIsInstance(confirmation, dict)
        self.assertEqual("confirmation", confirmation.get("type"))
        intent_engine = latest.body["result_ref"]["data"]["intent_engine"]
        self.assertEqual("user-delivered-module", intent_engine["source"])
        self.assertEqual("LLMTaskAnalyzer", intent_engine["component"])

        confirmed = self.client.request(
            "POST",
            self.url("application_gateway_url", f"/api/v1/confirmations/{confirmation['id']}/decisions"),
            {"decision": "confirm", "actor": self.actor(), "values": [10000, 2680.5]},
        )
        self.assertEqual(200, confirmed.status)
        self.assertEqual("succeeded", confirmed.body.get("status"))

        completed = self.client.request(
            "GET",
            self.url("application_gateway_url", f"/api/v1/tasks/{task_id}"),
        )
        self.assertEqual(200, completed.status)
        self.assertEqual("succeeded", completed.body.get("state"))
        self.assertEqual("rule.calculate", completed.body["result_ref"]["selected_capability"])
        self.assertEqual(12680.5, completed.body["result_ref"]["capability_result"]["value"])

        trace = self.client.request(
            "GET",
            self.url("application_gateway_url", f"/api/v1/traces/{envelope['trace_id']}/calls"),
        )
        self.assertEqual(200, trace.status)
        calls = trace.body.get("items", [])
        modules = {(item.get("source_module"), item.get("target_module")) for item in calls}
        for expected in {
            ("application-gateway", "engine-gateway"),
            ("engine-gateway", "intent-adapter"),
            ("intent-adapter", "intent-analysis-engine-original"),
            ("intent-analysis-engine-original", "foundation-gateway"),
            ("foundation-gateway", "model-dispatcher"),
            ("engine-gateway", "workflow-execution"),
            ("workflow-execution", "foundation-gateway"),
            ("foundation-gateway", "permission-adapter"),
            ("workflow-execution", "engine-gateway"),
            ("engine-gateway", "rule-adapter"),
        }:
            self.assertIn(expected, modules)
        self.assertTrue(all("request" in item and "response" in item for item in calls))

        # 自动化测试默认停在真人确认前，防止在未配置专用测试数据时产生副作用。
