from __future__ import annotations

import time
from urllib.request import urlopen

from acceptance.lib.envelope import make_envelope
from acceptance.tests.live_base import LiveTestCase


class LiveMultiCaseTest(LiveTestCase):
    def test_multi_case_page_has_chinese_module_io_labels(self) -> None:
        with urlopen(self.url("application_gateway_url", "/cases"), timeout=5) as response:
            page = response.read().decode("utf-8")
        self.assertIn("多案例全链路验收台", page)
        self.assertIn("模块接口输入输出", page)
        self.assertIn("接收到的内容（Request）", page)
        self.assertIn("输出的内容（Response）", page)

    def test_content_conversation_reaches_content_engine(self) -> None:
        envelope = make_envelope(
            actor=self.actor(),
            source_layer="business_application",
            source_module="chat-validation",
            target_layer="business_engine",
            target_module="engine-gateway",
            capability="intent.analyze",
            action="intent.analyze",
            request_type="execute",
            payload={"utterance": "为智能巡检终端写一份新品发布内部通知，面向销售团队。"},
        )
        submitted = self.client.request(
            "POST",
            self.url("application_gateway_url", "/api/v1/application/instructions"),
            envelope,
        )
        task_id = submitted.body["task_id"]
        task = None
        for _ in range(100):
            task = self.client.request(
                "GET", self.url("application_gateway_url", f"/api/v1/tasks/{task_id}")
            ).body
            if task.get("state") == "waiting_human":
                break
            time.sleep(0.4)
        self.assertIsNotNone(task)
        self.assertEqual("waiting_human", task.get("state"))
        intent = task["result_ref"]["data"]["tasks"][0]
        self.assertEqual("content.generate", intent["capability_code"])

        confirmed = self.client.request(
            "POST",
            self.url(
                "application_gateway_url",
                f"/api/v1/confirmations/{task['confirmation_ref']['id']}/decisions",
            ),
            {"decision": "confirm", "actor": self.actor()},
        )
        self.assertEqual(200, confirmed.status)
        data = confirmed.body["data"]
        self.assertEqual("content.generate", data["selected_capability"])
        self.assertTrue(data["capability_result"].get("content"))

        trace = self.client.request(
            "GET",
            self.url("application_gateway_url", f"/api/v1/traces/{envelope['trace_id']}/calls"),
        )
        targets = {item["target_module"] for item in trace.body["items"]}
        self.assertIn("permission-adapter", targets)
        self.assertIn("content-adapter", targets)
        self.assertIn("content-production-engine-original", targets)
        self.assertIn("model-dispatcher", targets)
        self.assertTrue(all("request" in item and "response" in item for item in trace.body["items"]))

    def test_rule_case_extracts_amounts_next_to_chinese_text(self) -> None:
        envelope = make_envelope(
            actor=self.actor(),
            source_layer="business_application",
            source_module="chat-validation",
            target_layer="business_engine",
            target_module="engine-gateway",
            capability="intent.analyze",
            action="intent.analyze",
            request_type="execute",
            payload={"utterance": "计算三笔项目费用合计，金额分别为1200元、350.5元和80元"},
        )
        submitted = self.client.request(
            "POST",
            self.url("application_gateway_url", "/api/v1/application/instructions"),
            envelope,
        )
        task_id = submitted.body["task_id"]
        task = None
        for _ in range(100):
            task = self.client.request(
                "GET", self.url("application_gateway_url", f"/api/v1/tasks/{task_id}")
            ).body
            if task.get("state") == "waiting_human":
                break
            time.sleep(0.4)
        self.assertIsNotNone(task)
        self.assertEqual("waiting_human", task.get("state"))
        intent = task["result_ref"]["data"]["tasks"][0]
        self.assertEqual("rule.calculate", intent["capability_code"])
        self.assertEqual([1200.0, 350.5, 80.0], intent["parameters"]["values"])
