from __future__ import annotations

import json
from pathlib import Path


def write_package(root: Path, blocks: list[dict], profile: str = "flow-document", table: dict | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "standard-document/v1",
        "document_id": "doc-test",
        "package_version": 1,
        "profile": profile,
        "status": "completed",
        "source": {"file_name": "test.docx", "sha256": "a" * 64},
        "business_tags": ["project:test"],
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "layout.json").write_text(json.dumps({
        "schema": "standard-document/v1",
        "reading_order": [block["block_id"] for block in blocks],
        "pages": [],
        "logical_blocks": [],
    }), encoding="utf-8")
    (root / "blocks.jsonl").write_text(
        "".join(json.dumps(block, ensure_ascii=False) + "\n" for block in blocks), encoding="utf-8"
    )
    if table is not None:
        table_path = root / "assets" / "tables" / "table-0001.json"
        table_path.parent.mkdir(parents=True, exist_ok=True)
        table_path.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
    return root

