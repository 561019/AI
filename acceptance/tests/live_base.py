from __future__ import annotations

import os
import unittest
from typing import Any

from acceptance.lib.config import load_config, token_from_env
from acceptance.lib.http_client import ApiClient


class LiveTestCase(unittest.TestCase):
    config: dict[str, Any]
    client: ApiClient

    @classmethod
    def setUpClass(cls) -> None:
        config = load_config(os.getenv("ACCEPTANCE_CONFIG"))
        if not config:
            raise unittest.SkipTest("未配置 ACCEPTANCE_CONFIG，真实接口测试未执行")
        cls.config = config
        cls.client = ApiClient(
            timeout=float(config.get("timeout_seconds", 10)),
            token=token_from_env(config, "access_token_env"),
        )

    def url(self, key: str, path: str) -> str:
        base = str(self.config.get(key, "")).rstrip("/")
        if not base:
            self.skipTest(f"配置缺少 {key}")
        return f"{base}/{path.lstrip('/')}"

    def actor(self) -> dict[str, Any]:
        return dict(self.config["test_actor"])

    def assert_standard_response(self, body: Any) -> None:
        self.assertIsInstance(body, dict)
        for field in ("status", "trace_id", "request_id"):
            self.assertIn(field, body)
        self.assertIn(body["status"], {"success", "accepted", "failed"})
