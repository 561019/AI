from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .config import ChunkSettings
from .models import Chunk
from .standard_package import StandardPackage


class ProcessStore:
    def __init__(self, output_root: Path):
        self.output_root = output_root.resolve()

    def save_chunks(self, package: StandardPackage, chunks: list[Chunk], settings: ChunkSettings) -> Path:
        destination = self.output_root / "chunk-documents" / package.document_id / f"v{package.package_version}"
        destination.mkdir(parents=True, exist_ok=True)
        normalized_path = destination / "normalized-blocks.jsonl"
        chunks_path = destination / "chunks.jsonl"
        trace_path = destination / "trace.jsonl"
        self._write_jsonl(normalized_path, package.normalized_block_records())
        self._write_jsonl(chunks_path, (chunk.to_dict() for chunk in chunks))
        self._write_jsonl(trace_path, (
            {
                "chunk_id": chunk.chunk_id,
                "chunk_index": chunk.chunk_index,
                "operation": "table-row-split" if chunk.chunk_type == "table" else "semantic-pack",
                "source_block_ids": chunk.source_block_ids,
                "table_row_start": chunk.table_row_start,
                "table_row_end": chunk.table_row_end,
                "eligible_for_embedding": chunk.eligible_for_embedding,
            }
            for chunk in chunks
        ))
        manifest = {
            "schema": "chunk-process/v1",
            "document_id": package.document_id,
            "source_package": {
                "schema": package.manifest["schema"],
                "package_version": package.package_version,
                "profile": package.profile,
                "source_sha256": package.source_sha256,
            },
            "strategy": {
                "version": settings.strategy_version,
                "target_tokens": settings.target_tokens,
                "max_tokens": settings.max_tokens,
                "min_tokens": settings.min_tokens,
                "overlap_tokens": settings.overlap_tokens,
                "token_counter": "mixed-cjk-latin-estimator/v1",
                "embed_review_required": settings.embed_review_required,
            },
            "statistics": {
                "source_blocks": len(package.blocks),
                "chunks": len(chunks),
                "eligible_for_embedding": sum(chunk.eligible_for_embedding for chunk in chunks),
                "review_required": sum(chunk.needs_review for chunk in chunks),
                "tables": sum(chunk.chunk_type == "table" for chunk in chunks),
            },
            "artifacts": {
                "normalized_blocks": normalized_path.name,
                "chunks": chunks_path.name,
                "trace": trace_path.name,
            },
            "checksums": {
                normalized_path.name: self._sha256(normalized_path),
                chunks_path.name: self._sha256(chunks_path),
                trace_path.name: self._sha256(trace_path),
            },
            "created_at": datetime.now(UTC).isoformat(),
        }
        self._write_json(destination / "manifest.json", manifest)
        return destination

    @staticmethod
    def load_chunks(process_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        manifest_path = process_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema") != "chunk-process/v1":
            raise ValueError("process manifest schema must be chunk-process/v1")
        chunks_name = manifest.get("artifacts", {}).get("chunks", "chunks.jsonl")
        chunks_path = process_dir / chunks_name
        chunks = [json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return manifest, chunks

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        ProcessStore._atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")

    @staticmethod
    def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
        content = "".join(json.dumps(record, ensure_ascii=False, default=str) + "\n" for record in records)
        ProcessStore._atomic_write(path, content)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for data in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(data)
        return digest.hexdigest()

