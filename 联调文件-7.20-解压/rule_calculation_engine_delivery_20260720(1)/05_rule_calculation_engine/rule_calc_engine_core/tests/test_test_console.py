from __future__ import annotations

import unittest
from pathlib import Path

class TestConsoleTests(unittest.TestCase):
    project_root = Path(__file__).resolve().parents[1]
    console_path = project_root / "app" / "static" / "test_console.html"
    main_path = project_root / "app" / "main.py"

    def test_console_file_contains_real_execution_call(self) -> None:
        self.assertTrue(self.console_path.is_file())
        body = self.console_path.read_text(encoding="utf-8")
        self.assertIn("规则计算引擎测试台", body)
        self.assertIn('fetch("/v1/executions"', body)

    def test_main_declares_console_and_root_routes(self) -> None:
        source = self.main_path.read_text(encoding="utf-8")
        self.assertIn('@app.get("/test-console"', source)
        self.assertIn('@app.get("/", include_in_schema=False)', source)
        self.assertIn('RedirectResponse(url="/test-console")', source)
        self.assertIn('candidate-skill-trial', source)


if __name__ == "__main__":
    unittest.main()
