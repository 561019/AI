from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from doc_table_engine.engine import DocumentTableEngine, ParseRequest
from doc_table_engine.security import StaticPermissionPolicy
from doc_table_engine.standard_document import StandardDocumentBuilder


class StandardDocumentTests(unittest.TestCase):
    def test_csv_builds_versioned_knowledge_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sales.csv"
            source.write_text("name,amount\nAlice,100\n", encoding="utf-8")
            policy = StaticPermissionPolicy({"alice": {"document:parse", "tag:project:test"}})
            result = DocumentTableEngine(root / "engine", permission_policy=policy).parse(
                ParseRequest(source, "alice", ["project:test"])
            )
            package = StandardDocumentBuilder().build(
                source, result, root / "standard-document" / "v1", "jobs/test/original.csv"
            )

            self.assertEqual(package.manifest["schema"], "standard-document/v1")
            self.assertEqual(package.manifest["profile"], "tabular-document")
            self.assertTrue((package.root / "document.md").is_file())
            self.assertTrue((package.root / "blocks.jsonl").is_file())
            self.assertTrue((package.root / "layout.json").is_file())
            table = json.loads((package.root / "assets" / "tables" / "table-0001.json").read_text(encoding="utf-8"))
            self.assertEqual(table["rows"], 2)
            self.assertEqual(table["columns"], 2)
            blocks = [json.loads(line) for line in (package.root / "blocks.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(blocks[0]["type"], "table")
            self.assertEqual(blocks[0]["asset_ref"], "assets/tables/table-0001.json")


if __name__ == "__main__":
    unittest.main()
