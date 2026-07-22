from __future__ import annotations

import argparse
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records: list[dict[str, str]] = []

    @staticmethod
    def _name(test: unittest.case.TestCase) -> str:
        return test.id()

    def addSuccess(self, test):
        super().addSuccess(test)
        self.records.append({"test": self._name(test), "status": "passed"})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.records.append({"test": self._name(test), "status": "skipped", "reason": reason})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records.append({"test": self._name(test), "status": "failed", "detail": self._exc_info_to_string(err, test)})

    def addError(self, test, err):
        super().addError(test, err)
        self.records.append({"test": self._name(test), "status": "error", "detail": self._exc_info_to_string(err, test)})


class RecordingRunner(unittest.TextTestRunner):
    resultclass = RecordingResult


def build_suite(mode: str) -> unittest.TestSuite:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    if mode in {"contract", "all"}:
        suite.addTests(loader.discover(str(ROOT / "acceptance" / "tests"), pattern="test_contracts.py", top_level_dir=str(ROOT)))
    if mode in {"live", "all"}:
        suite.addTests(loader.discover(str(ROOT / "acceptance" / "tests"), pattern="test_live_*.py", top_level_dir=str(ROOT)))
    return suite


def main() -> int:
    parser = argparse.ArgumentParser(description="运行平台框架验收测试")
    parser.add_argument("--mode", choices=("contract", "live", "all"), default="contract")
    parser.add_argument("--config", help="真实环境配置 JSON 路径")
    args = parser.parse_args()
    if args.config:
        os.environ["ACCEPTANCE_CONFIG"] = args.config

    started_at = datetime.now(timezone.utc)
    result = RecordingRunner(verbosity=2).run(build_suite(args.mode))
    finished_at = datetime.now(timezone.utc)
    summary = {
        "mode": args.mode,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "successful": result.wasSuccessful(),
        "run": result.testsRun,
        "passed": sum(item["status"] == "passed" for item in result.records),
        "failed": sum(item["status"] == "failed" for item in result.records),
        "errors": sum(item["status"] == "error" for item in result.records),
        "skipped": sum(item["status"] == "skipped" for item in result.records),
        "tests": result.records,
    }
    report_dir = ROOT / "acceptance" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"acceptance-{args.mode}-{started_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"REPORT={report_path}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
