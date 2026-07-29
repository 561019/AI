from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from chunk_vector_engine.chunker import SemanticChunker
from chunk_vector_engine.config import ChunkSettings
from chunk_vector_engine.pipeline import build_chunk_process
from chunk_vector_engine.process_store import ProcessStore
from chunk_vector_engine.standard_package import StandardPackage, open_standard_package

from helpers import write_package


class ChunkerTests(unittest.TestCase):
    def test_fixed_layout_does_not_merge_pages_and_skips_review_for_embedding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package_path = write_package(root / "standard", [
                self._block("b-1", "第一页第一段", 1),
                self._block("b-2", "第一页第二段", 1),
                self._block("b-3", "第二页低置信内容", 2, needs_review=True),
            ], profile="fixed-layout")
            chunks = SemanticChunker(ChunkSettings(target_tokens=100, max_tokens=120, min_tokens=1, overlap_tokens=10)).chunk(
                StandardPackage(package_path)
            )
            self.assertEqual(len(chunks), 2)
            self.assertEqual(chunks[0].page_start, 1)
            self.assertEqual(chunks[1].page_start, 2)
            self.assertFalse(chunks[1].eligible_for_embedding)

    def test_table_is_split_by_rows_and_repeats_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cells = []
            rows = [["name", "amount"], *[[f"customer-{index}", str(index * 100)] for index in range(1, 13)]]
            for row_index, row in enumerate(rows, start=1):
                for column_index, value in enumerate(row, start=1):
                    cells.append({"row": row_index, "column": column_index, "value": value})
            table = {
                "schema": "standard-document/v1/table", "name": "sales", "rows": len(rows), "columns": 2, "cells": cells,
            }
            package_path = write_package(root / "standard", [{
                **self._block("b-table", "sales", None),
                "type": "table", "asset_ref": "assets/tables/table-0001.json",
            }], profile="tabular-document", table=table)
            chunks = SemanticChunker(ChunkSettings(target_tokens=24, max_tokens=35, min_tokens=1, overlap_tokens=2)).chunk(
                StandardPackage(package_path)
            )
            self.assertGreater(len(chunks), 1)
            self.assertTrue(all("| name | amount |" in chunk.text for chunk in chunks))
            self.assertEqual(chunks[0].table_row_start, 2)
            self.assertEqual(chunks[-1].table_row_end, len(rows))

    def test_process_files_and_zip_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            standard = write_package(root / "standard-document" / "v1", [self._block("b-1", "正文内容", None)])
            archive = root / "standard.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                for path in standard.rglob("*"):
                    if path.is_file():
                        handle.write(path, path.relative_to(root).as_posix())
            with open_standard_package(archive) as package:
                self.assertEqual(package.document_id, "doc-test")
            destination = build_chunk_process(archive, root / "output", ChunkSettings(min_tokens=1))
            self.assertTrue((destination / "normalized-blocks.jsonl").is_file())
            self.assertTrue((destination / "chunks.jsonl").is_file())
            manifest, chunks = ProcessStore.load_chunks(destination)
            self.assertEqual(manifest["schema"], "chunk-process/v1")
            self.assertEqual(len(chunks), 1)

    @staticmethod
    def _block(block_id: str, text: str, page: int | None, needs_review: bool = False) -> dict:
        return {
            "block_id": block_id, "type": "paragraph", "order": int(block_id.split("-")[-1]) if block_id[-1].isdigit() else 1,
            "text": text, "page": page, "bbox": None, "confidence": 0.5 if needs_review else 1.0,
            "needs_review": needs_review, "heading_path": [], "source_ref": {"file_name": "test.pdf", "page": page},
        }


if __name__ == "__main__":
    unittest.main()

