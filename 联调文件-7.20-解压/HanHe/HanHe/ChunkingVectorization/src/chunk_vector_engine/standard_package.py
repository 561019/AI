from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator

from .models import StandardBlock


class StandardPackageError(ValueError):
    pass


class StandardPackage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.manifest = self._read_json(self.root / "manifest.json")
        if self.manifest.get("schema") != "standard-document/v1":
            raise StandardPackageError("manifest schema must be standard-document/v1")
        for key in ("document_id", "package_version", "profile", "source"):
            if key not in self.manifest:
                raise StandardPackageError(f"manifest is missing required field: {key}")
        self.layout = self._read_json(self.root / "layout.json")
        self.blocks = self._load_blocks()

    @property
    def document_id(self) -> str:
        return str(self.manifest["document_id"])

    @property
    def package_version(self) -> int:
        return int(self.manifest["package_version"])

    @property
    def profile(self) -> str:
        return str(self.manifest["profile"])

    @property
    def business_tags(self) -> list[str]:
        return [str(tag) for tag in self.manifest.get("business_tags", [])]

    @property
    def source_sha256(self) -> str:
        return str(self.manifest.get("source", {}).get("sha256", ""))

    def table(self, asset_ref: str) -> dict:
        path = self._safe_asset(asset_ref)
        payload = self._read_json(path)
        if not str(payload.get("schema", "")).endswith("/table"):
            raise StandardPackageError(f"invalid table asset schema: {asset_ref}")
        return payload

    def normalized_block_records(self) -> list[dict]:
        records = []
        for block in self.blocks:
            record = dict(block.raw)
            record["resolved_order"] = block.order
            records.append(record)
        return records

    def _load_blocks(self) -> list[StandardBlock]:
        path = self.root / "blocks.jsonl"
        if not path.is_file():
            raise StandardPackageError("blocks.jsonl does not exist")
        raw_blocks: list[dict] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                raw_blocks.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise StandardPackageError(f"invalid blocks.jsonl line {line_number}: {exc}") from exc

        by_id = {str(item.get("block_id")): item for item in raw_blocks}
        if len(by_id) != len(raw_blocks) or "None" in by_id:
            raise StandardPackageError("block_id values must be present and unique")
        reading_order = [str(item) for item in self.layout.get("reading_order", [])]
        unknown = [block_id for block_id in reading_order if block_id not in by_id]
        if unknown:
            raise StandardPackageError(f"layout references unknown blocks: {unknown[:3]}")
        ordered = [by_id[block_id] for block_id in reading_order]
        ordered.extend(sorted(
            (item for item in raw_blocks if str(item["block_id"]) not in set(reading_order)),
            key=lambda item: int(item.get("order", 0)),
        ))
        return [self._to_block(item, index) for index, item in enumerate(ordered, start=1)]

    @staticmethod
    def _to_block(item: dict, fallback_order: int) -> StandardBlock:
        source_ref = item.get("source_ref") if isinstance(item.get("source_ref"), dict) else {}
        return StandardBlock(
            block_id=str(item["block_id"]),
            block_type=str(item.get("type") or "paragraph"),
            order=int(item.get("order") or fallback_order),
            text=str(item.get("text") or "").strip(),
            page=int(item["page"]) if item.get("page") is not None else None,
            bbox=item.get("bbox"),
            confidence=float(item.get("confidence", 1.0)),
            needs_review=bool(item.get("needs_review", False)),
            heading_path=[str(value) for value in item.get("heading_path", [])],
            source_ref=source_ref,
            asset_ref=str(item["asset_ref"]) if item.get("asset_ref") else None,
            parquet_ref=str(item["parquet_ref"]) if item.get("parquet_ref") else None,
            field_name=str(item["field_name"]) if item.get("field_name") else None,
            target_field=str(item["target_field"]) if item.get("target_field") else None,
            raw=item,
        )

    def _safe_asset(self, relative: str) -> Path:
        parts = PurePosixPath(relative)
        if parts.is_absolute() or any(part in {"", ".", ".."} for part in parts.parts):
            raise StandardPackageError(f"unsafe asset path: {relative}")
        path = self.root.joinpath(*parts.parts).resolve()
        if self.root != path and self.root not in path.parents:
            raise StandardPackageError(f"asset escapes package root: {relative}")
        if not path.is_file():
            raise StandardPackageError(f"asset does not exist: {relative}")
        return path

    @staticmethod
    def _read_json(path: Path) -> dict:
        if not path.is_file():
            raise StandardPackageError(f"required file does not exist: {path.name}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StandardPackageError(f"invalid JSON file {path.name}: {exc}") from exc
        if not isinstance(payload, dict):
            raise StandardPackageError(f"JSON root must be an object: {path.name}")
        return payload


@contextmanager
def open_standard_package(source: Path) -> Iterator[StandardPackage]:
    source = source.resolve()
    if source.is_dir():
        yield StandardPackage(source)
        return
    if not source.is_file() or source.suffix.lower() != ".zip":
        raise StandardPackageError("package source must be an expanded directory or .zip file")

    temporary = Path(tempfile.mkdtemp(prefix="standard-document-"))
    try:
        with zipfile.ZipFile(source) as archive:
            for member in archive.infolist():
                relative = PurePosixPath(member.filename)
                if relative.is_absolute() or any(part == ".." for part in relative.parts):
                    raise StandardPackageError(f"unsafe ZIP member: {member.filename}")
                target = temporary.joinpath(*relative.parts).resolve()
                if temporary.resolve() != target and temporary.resolve() not in target.parents:
                    raise StandardPackageError(f"ZIP member escapes extraction root: {member.filename}")
            archive.extractall(temporary)
        manifests = list(temporary.rglob("manifest.json"))
        candidates = [path.parent for path in manifests if (path.parent / "blocks.jsonl").is_file()]
        if len(candidates) != 1:
            raise StandardPackageError("ZIP must contain exactly one standard-document package")
        yield StandardPackage(candidates[0])
    finally:
        shutil.rmtree(temporary, ignore_errors=True)

