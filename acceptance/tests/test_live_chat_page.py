from __future__ import annotations

from urllib.request import urlopen

from acceptance.tests.live_base import LiveTestCase


class LiveChatPageTest(LiveTestCase):
    def test_chat_page_is_served_by_application_gateway(self) -> None:
        with urlopen(self.url("application_gateway_url", "/chat"), timeout=5) as response:
            html = response.read().decode("utf-8")
            status = response.status
        self.assertEqual(200, status)
        self.assertIn("AI 平台全流程对话验收台", html)
        self.assertIn("/api/v1/application/instructions", html)
        self.assertIn("/api/v1/confirmations/", html)

    def test_trace_monitor_page_is_available(self) -> None:
        with urlopen(self.url("application_gateway_url", "/monitor"), timeout=5) as response:
            html = response.read().decode("utf-8")
            status = response.status
        self.assertEqual(200, status)
        self.assertIn("平台接口调用监控", html)
        self.assertIn("/api/v1/traces/", html)

    def test_full_framework_demo_page_is_available(self) -> None:
        with urlopen(self.url("application_gateway_url", "/demo"), timeout=5) as response:
            html = response.read().decode("utf-8")
            status = response.status
        self.assertEqual(200, status)
        self.assertIn("平台全链路案例验收", html)
        self.assertIn("接口传入内容", html)
        self.assertIn("/api/v1/application/instructions", html)
        self.assertIn("/api/v1/traces/", html)
