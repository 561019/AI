from __future__ import annotations

import re

from pydantic import BaseModel, Field


class TextUnit(BaseModel):
    text: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class TextChunk(BaseModel):
    chunk_index: int = Field(ge=0)
    text: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    units: list[TextUnit]


class LongTextDocument(BaseModel):
    original_text: str
    character_count: int
    length_category: str
    chunks: list[TextChunk]
    unit_count: int


class LongTextParser:
    """Splits arbitrary-length input into sentence-aligned overlapping chunks."""

    def __init__(self, *, chunk_size: int = 2000, chunk_overlap: int = 200) -> None:
        if chunk_size < 200:
            raise ValueError("chunk_size must be at least 200 characters")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be between 0 and chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def parse(self, text: str) -> LongTextDocument:
        original = str(text or "")
        units = self._split_units(original)
        chunks = self._build_chunks(units)
        return LongTextDocument(
            original_text=original,
            character_count=len(original),
            length_category=self._length_category(len(original)),
            chunks=chunks,
            unit_count=len(units),
        )

    def _split_units(self, text: str) -> list[TextUnit]:
        units: list[TextUnit] = []
        pattern = re.compile(r"[^。！？!?；;\n]+(?:[。！？!?；;]+|\n+|$)")
        for match in pattern.finditer(text):
            raw = match.group(0)
            leading = len(raw) - len(raw.lstrip())
            trailing = len(raw.rstrip())
            value = raw.strip()
            if not value:
                continue
            start = match.start() + leading
            end = match.start() + trailing
            units.extend(self._split_oversized_unit(value, start, end))
        return units

    def _split_oversized_unit(self, text: str, start: int, end: int) -> list[TextUnit]:
        if len(text) <= self.chunk_size:
            return [TextUnit(text=text, start=start, end=end)]

        result: list[TextUnit] = []
        cursor = 0
        while cursor < len(text):
            slice_end = min(cursor + self.chunk_size, len(text))
            if slice_end < len(text):
                boundary = max(
                    text.rfind("，", cursor, slice_end),
                    text.rfind(",", cursor, slice_end),
                    text.rfind(" ", cursor, slice_end),
                )
                if boundary > cursor + self.chunk_size // 2:
                    slice_end = boundary + 1
            value = text[cursor:slice_end].strip()
            if value:
                offset = text.find(value, cursor, slice_end)
                result.append(
                    TextUnit(
                        text=value,
                        start=start + offset,
                        end=start + offset + len(value),
                    )
                )
            cursor = slice_end
        return result

    def _build_chunks(self, units: list[TextUnit]) -> list[TextChunk]:
        if not units:
            return []

        chunks: list[TextChunk] = []
        current: list[TextUnit] = []
        current_size = 0
        for unit in units:
            projected = current_size + len(unit.text)
            if current and projected > self.chunk_size:
                chunks.append(self._make_chunk(len(chunks), current))
                current = self._overlap_units(current)
                current_size = sum(len(item.text) for item in current)
            current.append(unit)
            current_size += len(unit.text)

        if current:
            chunks.append(self._make_chunk(len(chunks), current))
        return chunks

    def _overlap_units(self, units: list[TextUnit]) -> list[TextUnit]:
        if self.chunk_overlap == 0:
            return []
        selected: list[TextUnit] = []
        size = 0
        for unit in reversed(units):
            if selected and size + len(unit.text) > self.chunk_overlap:
                break
            selected.append(unit)
            size += len(unit.text)
        return list(reversed(selected))

    def _make_chunk(self, index: int, units: list[TextUnit]) -> TextChunk:
        return TextChunk(
            chunk_index=index,
            text="".join(unit.text for unit in units),
            start=units[0].start,
            end=units[-1].end,
            units=list(units),
        )

    def _length_category(self, length: int) -> str:
        if length < 1000:
            return "short"
        if length <= 10000:
            return "medium"
        return "long"
