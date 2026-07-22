from __future__ import annotations

from uuid import uuid4

from acceptance.tests.live_base import LiveTestCase


class LiveModelDispatcherTest(LiveTestCase):
    def test_intent_request_uses_unified_model_contract(self) -> None:
        trace_id = str(uuid4())
        result = self.client.request(
            "POST",
            self.url("model_dispatcher_url", "/api/v1/models/responses"),
            {
                "trace_id": trace_id,
                "actor": self.actor(),
                "task_type": "intent_analysis",
                "messages": [
                    {"role": "system", "content": "只输出 JSON 对象，字段包含 capability_code、description、confidence、clarification_required、parameters；capability_code 必须为 rule.calculate。"},
                    {"role": "user", "content": "计算七月份销售提成"},
                ],
                "response_schema": {"type": "object"},
                "model_policy": {"quality_level": "standard", "allow_fallback": True, "sensitive_data": False},
            },
        )
        self.assertEqual(200, result.status)
        self.assertEqual(trace_id, result.body.get("trace_id"))
        self.assertEqual("rule.calculate", result.body["output"]["capability_code"])
        self.assertIn(result.body.get("provider"), {"local-mock", "deepseek"})
