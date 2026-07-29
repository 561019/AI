from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .config import ChunkSettings
from .models import Chunk, StandardBlock
from .standard_package import StandardPackage
from .tokenization import EstimatedTokenizer


@dataclass(frozen=True)
class _Piece:
    text: str
    blocks: tuple[StandardBlock, ...]
    chunk_type: str
    table_row_start: int | None = None
    table_row_end: int | None = None


class SemanticChunker:
    def __init__(self, settings: ChunkSettings | None = None, tokenizer: EstimatedTokenizer | None = None):
        self.settings = settings or ChunkSettings()
        self.settings.validate()
        self.tokenizer = tokenizer or EstimatedTokenizer()

    def chunk(self, package: StandardPackage) -> list[Chunk]:
        pieces: list[_Piece] = []
        buffer: list[_Piece] = []

        def flush() -> None:
            nonlocal buffer
            if buffer:
                pieces.append(self._merge_pieces(buffer))
                buffer = []

        for block in package.blocks:
            if block.block_type == "table":
                flush()
                pieces.extend(self._table_pieces(package, block))
                continue
            if block.block_type == "field":
                flush()
                label = block.field_name or block.target_field or "field"
                text = f"{label}: {block.text}" if label and block.text else block.text
                pieces.extend(_Piece(part, (block,), "field") for part in self._split(text))
                continue
            if not block.text:
                continue
            for part in self._split(block.text):
                candidate = _Piece(part, (block,), "text")
                if buffer and not self._compatible(package.profile, buffer[-1].blocks[-1], block):
                    flush()
                candidate_tokens = self.tokenizer.count(self._joined_text([*buffer, candidate]))
                current_tokens = self.tokenizer.count(self._joined_text(buffer))
                if buffer and candidate_tokens > self.settings.target_tokens:
                    if current_tokens < self.settings.min_tokens and candidate_tokens <= self.settings.max_tokens:
                        buffer.append(candidate)
                        flush()
                    else:
                        flush()
                        buffer.append(candidate)
                else:
                    buffer.append(candidate)
        flush()

        chunks: list[Chunk] = []
        for index, piece in enumerate(pieces, start=1):
            chunks.append(self._to_chunk(package, piece, index))
        return chunks

    def _split(self, text: str) -> list[str]:
        return self.tokenizer.split_text(text, self.settings.max_tokens, self.settings.overlap_tokens)

    def _compatible(self, profile: str, previous: StandardBlock, current: StandardBlock) -> bool:
        if previous.heading_path != current.heading_path:
            return False
        if profile in {"fixed-layout", "slide-document"} and previous.page != current.page:
            return False
        return previous.needs_review == current.needs_review

    @staticmethod
    def _joined_text(pieces: list[_Piece]) -> str:
        return "\n\n".join(piece.text for piece in pieces if piece.text)

    def _merge_pieces(self, pieces: list[_Piece]) -> _Piece:
        blocks: list[StandardBlock] = []
        seen: set[str] = set()
        for piece in pieces:
            for block in piece.blocks:
                if block.block_id not in seen:
                    seen.add(block.block_id)
                    blocks.append(block)
        return _Piece(self._joined_text(pieces), tuple(blocks), "text")

    def _table_pieces(self, package: StandardPackage, block: StandardBlock) -> list[_Piece]:
        if not block.asset_ref:
            return [_Piece(f"Table: {block.text}", (block,), "table")]
        table = package.table(block.asset_ref)
        row_count = int(table.get("rows") or 0)
        column_count = int(table.get("columns") or 0)
        cells = table.get("cells", [])
        lookup = {
            (int(cell.get("row") or 0), int(cell.get("column") or 0)): self._cell_text(cell.get("value"))
            for cell in cells
            if isinstance(cell, dict)
        }
        rows = [[lookup.get((row, column), "") for column in range(1, column_count + 1)] for row in range(1, row_count + 1)]
        if not rows:
            return [_Piece(f"Table: {table.get('name') or block.text}", (block,), "table")]

        title = f"Table: {table.get('name') or block.text}"
        header = rows[0]
        data_rows = rows[1:]
        if not data_rows:
            return [_Piece(self._table_markdown(title, header, []), (block,), "table", 1, 1)]

        result: list[_Piece] = []
        current: list[list[str]] = []
        start_row = 2
        for row_number, row in enumerate(data_rows, start=2):
            candidate = [*current, row]
            candidate_text = self._table_markdown(title, header, candidate)
            if current and self.tokenizer.count(candidate_text) > self.settings.target_tokens:
                result.extend(self._bounded_table_piece(title, header, current, block, start_row, row_number - 1))
                current = [row]
                start_row = row_number
            else:
                current = candidate
        if current:
            result.extend(self._bounded_table_piece(title, header, current, block, start_row, start_row + len(current) - 1))
        return result

    def _bounded_table_piece(
        self,
        title: str,
        header: list[str],
        rows: list[list[str]],
        block: StandardBlock,
        start_row: int,
        end_row: int,
    ) -> list[_Piece]:
        text = self._table_markdown(title, header, rows)
        return [
            _Piece(part, (block,), "table", start_row, end_row)
            for part in self._split(text)
        ]

    @staticmethod
    def _cell_text(value: Any) -> str:
        return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ").strip()

    @staticmethod
    def _table_markdown(title: str, header: list[str], rows: list[list[str]]) -> str:
        width = max(1, len(header))
        safe_header = header or [f"column_{index}" for index in range(1, width + 1)]
        lines = [title, "| " + " | ".join(safe_header) + " |", "| " + " | ".join(["---"] * width) + " |"]
        lines.extend("| " + " | ".join(row) + " |" for row in rows)
        return "\n".join(lines)

    def _to_chunk(self, package: StandardPackage, piece: _Piece, index: int) -> Chunk:
        blocks = list(piece.blocks)
        pages = [block.page for block in blocks if block.page is not None]
        source_refs = self._unique_dicts([block.source_ref for block in blocks if block.source_ref])
        asset_refs = list(dict.fromkeys(block.asset_ref for block in blocks if block.asset_ref))
        source_ids = list(dict.fromkeys(block.block_id for block in blocks))
        headings = blocks[0].heading_path if blocks else []
        needs_review = any(block.needs_review for block in blocks)
        confidence = sum(block.confidence for block in blocks) / len(blocks) if blocks else 1.0
        embedding_text = "\n".join([*headings, piece.text]).strip()
        identity = {
            "document_id": package.document_id,
            "package_version": package.package_version,
            "strategy": self.settings.strategy_version,
            "source_block_ids": source_ids,
            "table_rows": [piece.table_row_start, piece.table_row_end],
            "text_sha256": hashlib.sha256(piece.text.encode("utf-8")).hexdigest(),
        }
        chunk_id = hashlib.sha256(
            json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return Chunk(
            chunk_id=chunk_id,
            document_id=package.document_id,
            package_version=package.package_version,
            chunk_index=index,
            chunk_type=piece.chunk_type,
            text=piece.text,
            embedding_text=embedding_text,
            token_count=self.tokenizer.count(embedding_text),
            source_block_ids=source_ids,
            heading_path=headings,
            page_start=min(pages) if pages else None,
            page_end=max(pages) if pages else None,
            source_refs=source_refs,
            asset_refs=asset_refs,
            confidence=round(confidence, 6),
            needs_review=needs_review,
            eligible_for_embedding=not needs_review or self.settings.embed_review_required,
            business_tags=package.business_tags,
            source_sha256=package.source_sha256,
            strategy_version=self.settings.strategy_version,
            table_row_start=piece.table_row_start,
            table_row_end=piece.table_row_end,
        )

    @staticmethod
    def _unique_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            identity = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
            if identity not in seen:
                seen.add(identity)
                result.append(item)
        return result

