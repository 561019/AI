from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from doc_table_engine.engine import DocumentTableEngine, ParseRequest
from doc_table_engine.models import ParseRoute, ParseStatus
from doc_table_engine.security import PermissionDenied, StaticPermissionPolicy


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.policy = StaticPermissionPolicy({
            "alice": {"document:parse", "tag:project:test", "tag:reimbursement:test"}
        })

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_direct_csv_preserves_value_and_source(self) -> None:
        source = self.root / "sales.csv"
        source.write_text("区域,销售额\n华东,125000.00\n", encoding="utf-8")
        engine = DocumentTableEngine(self.output, permission_policy=self.policy)
        result = engine.parse(ParseRequest(source, "alice", ["project:test"]))
        self.assertEqual(result.registration.route, ParseRoute.DIRECT)
        self.assertEqual(result.registration.status, ParseStatus.COMPLETED)
        amount = next(v for v in result.semantic.tables[0].values if v.source.cell == "R2C2")
        self.assertEqual(amount.raw_value, "125000.00")
        self.assertEqual(amount.source.file_sha256, result.original.sha256)
        self.assertTrue(Path(result.original.stored_path).exists())
        self.assertTrue(engine.audit.verify())

    def test_template_mapping_is_versioned(self) -> None:
        source = self.root / "expense.csv"
        source.write_text("发票号,金额,日期\nINV-1,1280.50,2026-07-01\n", encoding="utf-8")
        template = self.root / "template.json"
        template.write_text(json.dumps({
            "template_id": "expense",
            "version": "1.2.0",
            "document_type": "expense",
            "fields": [{
                "name": "金额",
                "target_field": "form.amount",
                "selector": {"type": "header", "header": "金额", "row_offset": 1},
                "required": True,
            }],
        }, ensure_ascii=False), encoding="utf-8")
        engine = DocumentTableEngine(self.output, permission_policy=self.policy)
        result = engine.parse(ParseRequest(source, "alice", ["reimbursement:test"], template))
        self.assertEqual(result.registration.route, ParseRoute.TEMPLATE)
        self.assertEqual(result.registration.template_version, "1.2.0")
        self.assertEqual(result.semantic.fields[0].raw_value, "1280.50")
        self.assertEqual(result.semantic.fields[0].target_field, "form.amount")

    def test_low_confidence_ocr_requires_review(self) -> None:
        image = self.root / "scan.png"
        image.write_bytes(b"demo-image")
        sidecar = Path(str(image) + ".ocr.json")
        sidecar.write_text(json.dumps({"blocks": [{
            "page": 1,
            "bbox": [1, 2, 3, 4],
            "text": "不确定字段",
            "confidence": 0.55,
        }]}, ensure_ascii=False), encoding="utf-8")
        engine = DocumentTableEngine(self.output, permission_policy=self.policy)
        result = engine.parse(ParseRequest(image, "alice", ["project:test"], confidence_threshold=0.85))
        self.assertEqual(result.registration.route, ParseRoute.OCR)
        self.assertEqual(result.registration.status, ParseStatus.REVIEW_REQUIRED)
        self.assertTrue(result.semantic.text_blocks[0].needs_review)
        self.assertFalse(result.semantic.text_blocks[0].auto_fill_allowed)

    def test_permission_checked_before_parse(self) -> None:
        source = self.root / "sales.csv"
        source.write_text("a,b\n1,2\n", encoding="utf-8")
        engine = DocumentTableEngine(self.output, permission_policy=self.policy)
        with self.assertRaises(PermissionDenied):
            engine.parse(ParseRequest(source, "bob", ["project:test"]))

    def test_markdown_and_json_are_cleaned_into_traceable_values(self) -> None:
        markdown = self.root / "note.md"
        markdown.write_text("# Title\n\nName | Amount\n--- | ---\n Alice  |  100 \n", encoding="utf-8")
        engine = DocumentTableEngine(self.output, permission_policy=self.policy)
        md_result = engine.parse(ParseRequest(markdown, "alice", ["project:test"]))
        self.assertEqual(md_result.semantic.text_blocks[0].raw_value, "Title")
        self.assertEqual(md_result.semantic.tables[0].values[-1].raw_value, "100")

        source = self.root / "data.json"
        source.write_text('{"customer": {"name": " Alice  ", "amount": 100}}', encoding="utf-8")
        json_result = engine.parse(ParseRequest(source, "alice", ["project:test"]))
        values = {value.field_name: value.raw_value for value in json_result.semantic.tables[0].values}
        self.assertEqual(values["$.customer.name"], "Alice")
        self.assertEqual(values["$.customer.amount"], 100)


if __name__ == "__main__":
    unittest.main()
