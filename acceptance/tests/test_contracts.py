from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"


class ContractFilesTest(unittest.TestCase):
    def test_required_contract_files_exist(self) -> None:
        required = {
            "common-envelope.openapi.yaml",
            "layer-gateways.openapi.yaml",
            "identity-permission.openapi.yaml",
            "intent-analysis.openapi.yaml",
            "workflow-execution.openapi.yaml",
            "rule-calculation.openapi.yaml",
            "model-gateway.openapi.yaml",
            "capability-registry.openapi.yaml",
        }
        missing = sorted(name for name in required if not (CONTRACTS / name).is_file())
        self.assertEqual([], missing, f"缺少契约文件：{missing}")

    def test_openapi_headers_and_local_references(self) -> None:
        missing_refs: list[str] = []
        for path in CONTRACTS.glob("*.yaml"):
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("openapi: 3.1.0"), path.name)
            for relative in re.findall(r"\./([^'#\s]+\.yaml)#", text):
                if not (path.parent / relative).is_file():
                    missing_refs.append(f"{path.name} -> {relative}")
        self.assertEqual([], missing_refs)

    def test_operation_ids_are_unique(self) -> None:
        operations: list[str] = []
        for path in CONTRACTS.glob("*.yaml"):
            text = path.read_text(encoding="utf-8")
            operations.extend(re.findall(r"^\s+operationId:\s+([^\s]+)", text, re.MULTILINE))
        duplicates = sorted({item for item in operations if operations.count(item) > 1})
        self.assertGreater(len(operations), 0)
        self.assertEqual([], duplicates)

    def test_common_envelope_contains_architecture_fields(self) -> None:
        text = (CONTRACTS / "common-envelope.openapi.yaml").read_text(encoding="utf-8")
        for field in (
            "protocol_version",
            "message_id",
            "request_id",
            "trace_id",
            "source",
            "target",
            "actor",
            "request_type",
            "action",
            "payload",
            "expected_response",
            "idempotency_key",
            "deadline_at",
        ):
            self.assertIn(field, text)

    def test_async_states_are_consistent(self) -> None:
        common = (CONTRACTS / "common-envelope.openapi.yaml").read_text(encoding="utf-8")
        workflow = (CONTRACTS / "workflow-execution.openapi.yaml").read_text(encoding="utf-8")
        for state in (
            "accepted",
            "running",
            "waiting_dependency",
            "waiting_human",
            "succeeded",
            "failed",
            "cancelled",
        ):
            self.assertIn(state, common)
            self.assertIn(state, workflow)

    def test_three_layer_gateways_exist(self) -> None:
        text = (CONTRACTS / "layer-gateways.openapi.yaml").read_text(encoding="utf-8")
        for path in (
            "/api/v1/application/instructions",
            "/api/v1/engine/instructions",
            "/api/v1/foundation/instructions",
        ):
            self.assertIn(path, text)


if __name__ == "__main__":
    unittest.main()
