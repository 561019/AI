"""Build the versioned standard-document package consumed by later chunking."""
from __future__ import annotations

import json
import mimetypes
import shutil
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import ParseResult, ParsedTable, ParsedValue


SCHEMA_VERSION = "standard-document/v1"
PACKAGE_VERSION = 1


@dataclass(frozen=True)
class BuiltStandardDocument:
    root: Path
    manifest: dict[str, Any]
    files: list[Path]


class StandardDocumentBuilder:
    def build(self, source: Path, result: ParseResult, destination: Path, source_object_key: str) -> BuiltStandardDocument:
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "source").mkdir(exist_ok=True)
        (destination / "pages").mkdir(exist_ok=True)
        (destination / "assets" / "images").mkdir(parents=True, exist_ok=True)
        (destination / "assets" / "tables").mkdir(parents=True, exist_ok=True)

        profile = self._profile(source.suffix.lower())
        source_ref = {
            "file_name": result.original.file_name,
            "media_type": result.original.media_type,
            "size_bytes": result.original.size_bytes,
            "sha256": result.original.sha256,
            "object_key": source_object_key,
        }
        self._write_json(destination / "source" / "reference.json", source_ref)

        blocks, markdown, layout = self._build_semantic_files(result, destination)
        (destination / "document.md").write_text(markdown, encoding="utf-8")
        with (destination / "blocks.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for block in blocks:
                handle.write(json.dumps(block, ensure_ascii=False, default=str) + "\n")
        self._write_json(destination / "layout.json", layout)

        warnings: list[str] = []
        preview_count = self._create_page_previews(source, destination / "pages", warnings)
        image_count = self._extract_embedded_images(source, destination / "assets" / "images", warnings)

        artifact_paths = sorted(
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file() and path.name != "manifest.json"
        )
        manifest = {
            "schema": SCHEMA_VERSION,
            "document_id": result.registration.job_id,
            "package_version": PACKAGE_VERSION,
            "profile": profile,
            "status": str(result.registration.status),
            "source": source_ref,
            "parser": {
                "engine": "doc-table-engine",
                "engine_version": "0.3.0",
                "route": str(result.registration.route),
                "ocr_provider": "SiliconFlow/PaddlePaddle/PaddleOCR-VL-1.5" if str(result.registration.route) == "ocr" else None,
            },
            "statistics": {
                "pages": max(preview_count, max((int(block.get("page") or 0) for block in blocks), default=0)),
                "blocks": len(blocks),
                "tables": len(result.semantic.tables),
                "images": image_count,
                "review_required": result.registration.review_count,
            },
            "business_tags": result.registration.business_tags,
            "created_at": datetime.now(UTC).isoformat(),
            "artifacts": artifact_paths,
            "warnings": warnings,
        }
        self._write_json(destination / "manifest.json", manifest)
        files = sorted(path for path in destination.rglob("*") if path.is_file())
        return BuiltStandardDocument(destination, manifest, files)

    def _build_semantic_files(self, result: ParseResult, destination: Path) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        markdown_parts = [f"# {Path(result.original.file_name).stem}", ""]
        order = 0

        def add_value(value: ParsedValue, block_type: str) -> None:
            nonlocal order
            order += 1
            block_id = f"b-{order:06d}"
            source = asdict(value.source)
            block = {
                "block_id": block_id,
                "type": block_type,
                "order": order,
                "parent_id": None,
                "heading_path": [],
                "text": str(value.raw_value),
                "value_type": value.value_type,
                "field_name": value.field_name,
                "target_field": value.target_field,
                "page": source.get("page"),
                "bbox": source.get("bbox"),
                "confidence": value.confidence,
                "needs_review": value.needs_review,
                "source_ref": source,
            }
            blocks.append(block)
            markdown_parts.extend([f"<!-- block:{block_id} -->", str(value.raw_value), ""])

        for value in result.semantic.text_blocks:
            add_value(value, "paragraph")
        for value in result.semantic.fields:
            add_value(value, "field")
        for table_index, table in enumerate(result.semantic.tables, start=1):
            order += 1
            block_id = f"b-{order:06d}"
            asset_ref = f"assets/tables/table-{table_index:04d}.json"
            table_payload = self._table_payload(table_index, table)
            self._write_json(destination / asset_ref, table_payload)
            parquet_ref = self._write_parquet(destination, table_index, table_payload)
            source_values = [value for value in table.values if value.source.page or value.source.bbox]
            page = source_values[0].source.page if source_values else None
            bbox = source_values[0].source.bbox if source_values else None
            confidence = sum(value.confidence for value in table.values) / len(table.values) if table.values else 1.0
            block = {
                "block_id": block_id,
                "type": "table",
                "order": order,
                "parent_id": None,
                "heading_path": [],
                "text": table.name,
                "page": page,
                "bbox": bbox,
                "confidence": confidence,
                "asset_ref": asset_ref,
                "parquet_ref": parquet_ref,
                "source_ref": {"file_sha256": result.original.sha256, "file_name": result.original.file_name, "table": table_index},
            }
            blocks.append(block)
            markdown_parts.extend([f"<!-- block:{block_id} -->", f"## 表格：{table.name}", f"[结构化表格]({asset_ref})", ""])

        pages: dict[str, list[dict[str, Any]]] = {}
        logical_blocks: list[dict[str, Any]] = []
        for block in blocks:
            item = {key: block.get(key) for key in ("block_id", "type", "order", "bbox")}
            if block.get("page"):
                pages.setdefault(str(block["page"]), []).append(item)
            else:
                logical_blocks.append(item)
        layout = {
            "schema": SCHEMA_VERSION,
            "coordinate_system": "normalized-1000",
            "reading_order": [block["block_id"] for block in blocks],
            "pages": [{"page": int(page), "blocks": items} for page, items in sorted(pages.items(), key=lambda item: int(item[0]))],
            "logical_blocks": logical_blocks,
        }
        return blocks, "\n".join(markdown_parts).rstrip() + "\n", layout

    @staticmethod
    def _table_payload(table_index: int, table: ParsedTable) -> dict[str, Any]:
        max_row = max((value.source.row or 0 for value in table.values), default=0)
        max_column = max((value.source.column or 0 for value in table.values), default=0)
        cells = []
        for value in table.values:
            cells.append({
                "row": value.source.row,
                "column": value.source.column,
                "value": value.raw_value,
                "value_type": value.value_type,
                "row_span": 1,
                "column_span": 1,
                "confidence": value.confidence,
                "needs_review": value.needs_review,
                "source": asdict(value.source),
            })
        return {"schema": f"{SCHEMA_VERSION}/table", "table_id": f"table-{table_index:04d}", "name": table.name, "rows": max_row, "columns": max_column, "cells": cells}

    @staticmethod
    def _write_parquet(destination: Path, table_index: int, table_payload: dict[str, Any]) -> str | None:
        if not table_payload["rows"] or not table_payload["columns"]:
            return None
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            return None
        lookup = {(cell["row"], cell["column"]): cell["value"] for cell in table_payload["cells"]}
        rows = [
            {f"column_{column}": str(lookup.get((row, column), "")) for column in range(1, table_payload["columns"] + 1)}
            for row in range(1, table_payload["rows"] + 1)
        ]
        relative = f"assets/tables/table-{table_index:04d}.parquet"
        pq.write_table(pa.Table.from_pylist(rows), destination / relative)
        return relative

    @staticmethod
    def _create_page_previews(source: Path, pages_dir: Path, warnings: list[str]) -> int:
        if source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}:
            if source.suffix.lower() in {".pdf", ".pptx"}:
                warnings.append("page previews were not rendered because no document renderer is configured")
            return 0
        try:
            from PIL import Image, ImageSequence
            with Image.open(source) as image:
                count = 0
                for index, frame in enumerate(ImageSequence.Iterator(image), start=1):
                    frame.convert("RGB").save(pages_dir / f"page-{index:04d}.webp", "WEBP", quality=85)
                    count += 1
                return count
        except Exception as exc:
            warnings.append(f"page preview generation failed: {type(exc).__name__}")
            return 0

    @staticmethod
    def _extract_embedded_images(source: Path, images_dir: Path, warnings: list[str]) -> int:
        roots = {".docx": "word/media/", ".pptx": "ppt/media/", ".xlsx": "xl/media/", ".xlsm": "xl/media/"}
        media_root = roots.get(source.suffix.lower())
        if not media_root:
            return 0
        try:
            count = 0
            with zipfile.ZipFile(source) as archive:
                for name in sorted(entry for entry in archive.namelist() if entry.startswith(media_root) and not entry.endswith("/")):
                    extension = Path(name).suffix.lower()
                    if extension not in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".svg", ".emf", ".wmf"}:
                        continue
                    count += 1
                    target = images_dir / f"img-{count:04d}{extension}"
                    with archive.open(name) as source_handle, target.open("wb") as target_handle:
                        shutil.copyfileobj(source_handle, target_handle)
                    metadata = {"image_id": f"img-{count:04d}", "source_archive_path": name, "media_type": mimetypes.guess_type(target.name)[0] or "application/octet-stream"}
                    StandardDocumentBuilder._write_json(images_dir / f"img-{count:04d}.json", metadata)
            return count
        except (OSError, zipfile.BadZipFile) as exc:
            warnings.append(f"embedded image extraction failed: {type(exc).__name__}")
            return 0

    @staticmethod
    def _profile(suffix: str) -> str:
        if suffix in {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}:
            return "fixed-layout"
        if suffix == ".pptx":
            return "slide-document"
        if suffix in {".xlsx", ".xlsm", ".xls", ".csv", ".tsv"}:
            return "tabular-document"
        if suffix == ".json":
            return "structured-data"
        return "flow-document"

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
