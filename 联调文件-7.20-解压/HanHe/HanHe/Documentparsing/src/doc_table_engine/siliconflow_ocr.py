"""SiliconFlow-hosted PaddleOCR-VL-1.5 adapter."""
from __future__ import annotations

import base64
import io
import math
import re
import time
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx

from .models import ParsedContent, ParsedTable, ParsedValue, SourceRef
from .parsers import clean_text


class _TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._colspan = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
            try:
                self._colspan = max(1, int(dict(attrs).get("colspan") or "1"))
            except ValueError:
                self._colspan = 1
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            value = clean_text("".join(self._cell))
            self._row.append(str(value))
            self._row.extend([""] * (self._colspan - 1))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


class SiliconFlowPaddleOCRProvider:
    """Render pages locally and send only page images to SiliconFlow.

    No OCR or VLM weights are installed locally. SiliconFlow does not return a
    calibrated confidence score or detector-level boxes, so values use a
    configured conservative confidence and a full-page normalized bbox.
    """

    def __init__(
        self,
        api_key: str | None,
        base_url: str = "https://api.siliconflow.cn/v1",
        model: str = "PaddlePaddle/PaddleOCR-VL-1.5",
        timeout_seconds: float = 180,
        max_retries: int = 3,
        max_tokens: int = 8192,
        default_confidence: float = 0.80,
        pdf_render_dpi: int = 144,
        pdf_max_pages: int = 100,
        max_image_pixels: int = 4_000_000,
    ):
        if not 0 <= default_confidence <= 1:
            raise ValueError("OCR default confidence must be between 0 and 1")
        if pdf_render_dpi < 72 or pdf_render_dpi > 300:
            raise ValueError("PDF_RENDER_DPI must be between 72 and 300")
        if pdf_max_pages <= 0 or max_image_pixels <= 0 or max_tokens <= 0:
            raise ValueError("OCR page, pixel, and token limits must be positive")
        self.api_key = api_key
        self.endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self.model = model
        self.max_retries = max_retries
        self.max_tokens = max_tokens
        self.default_confidence = default_confidence
        self.pdf_render_dpi = pdf_render_dpi
        self.pdf_max_pages = pdf_max_pages
        self.max_image_pixels = max_image_pixels
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.client = httpx.Client(headers=headers, timeout=timeout_seconds)

    def close(self) -> None:
        self.client.close()

    def recognize(self, path: Path, file_hash: str) -> ParsedContent:
        if not self.api_key:
            raise RuntimeError("SILICONFLOW_API_KEY is required for PDF and image OCR")
        text_blocks: list[ParsedValue] = []
        tables: list[ParsedTable] = []
        pages = self._render_pages(path)
        for page_number, image_bytes in enumerate(pages, start=1):
            content = self._recognize_page(image_bytes)
            page_blocks, page_tables = self._parse_page(content, path, file_hash, page_number, len(tables))
            text_blocks.extend(page_blocks)
            tables.extend(page_tables)
        if not text_blocks and not tables:
            raise RuntimeError("SiliconFlow PaddleOCR-VL-1.5 returned no document content")
        return ParsedContent(
            text_blocks=text_blocks,
            tables=tables,
            ai_structured={
                "provider": "SiliconFlow",
                "model": self.model,
                "page_count": len(pages),
                "confidence_note": "SiliconFlow response has no calibrated confidence; configured default applied",
            },
        )

    def _recognize_page(self, image_bytes: bytes) -> str:
        data_uri = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri, "detail": "high"}},
                    {"type": "text", "text": "OCR:"},
                ],
            }],
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        response: httpx.Response | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.post(self.endpoint, json=payload)
                if response.status_code not in {408, 409, 429} and response.status_code < 500:
                    response.raise_for_status()
                    break
                response.raise_for_status()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError):
                if attempt >= self.max_retries:
                    raise
                retry_after = self._retry_after(response)
                time.sleep(retry_after if retry_after is not None else min(2**attempt, 8))
        if response is None:
            raise RuntimeError("SiliconFlow OCR request did not produce a response")
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("SiliconFlow returned an invalid chat completion response") from exc
        if isinstance(content, list):
            content = "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
        content = str(content or "").strip()
        content = re.sub(r"^```(?:markdown|html)?\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content).strip()
        if not content:
            raise RuntimeError("SiliconFlow PaddleOCR-VL-1.5 returned an empty page")
        return content

    def _render_pages(self, path: Path) -> list[bytes]:
        if path.suffix.lower() == ".pdf":
            return self._render_pdf(path)
        return self._render_image(path)

    def _render_pdf(self, path: Path) -> list[bytes]:
        try:
            import pymupdf
        except ImportError as exc:
            raise RuntimeError("PDF OCR requires PyMuPDF") from exc
        pages: list[bytes] = []
        with pymupdf.open(path) as document:
            if document.needs_pass:
                raise ValueError("password-protected PDF is not supported")
            if document.page_count > self.pdf_max_pages:
                raise ValueError(f"PDF exceeds PDF_MAX_PAGES={self.pdf_max_pages}")
            matrix = pymupdf.Matrix(self.pdf_render_dpi / 72, self.pdf_render_dpi / 72)
            for page in document:
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                pages.append(self._normalize_image(pixmap.tobytes("png")))
        return pages

    def _render_image(self, path: Path) -> list[bytes]:
        from PIL import Image, ImageOps, ImageSequence

        pages: list[bytes] = []
        with Image.open(path) as image:
            for frame_number, frame in enumerate(ImageSequence.Iterator(image), start=1):
                if frame_number > self.pdf_max_pages:
                    raise ValueError(f"image exceeds PDF_MAX_PAGES={self.pdf_max_pages}")
                output = io.BytesIO()
                normalized = ImageOps.exif_transpose(frame.copy()).convert("RGB")
                normalized.save(output, format="PNG", optimize=True)
                pages.append(self._normalize_image(output.getvalue()))
        return pages

    def _normalize_image(self, image_bytes: bytes) -> bytes:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as image:
            image = image.convert("RGB")
            pixels = image.width * image.height
            if pixels > self.max_image_pixels:
                scale = math.sqrt(self.max_image_pixels / pixels)
                size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
                image = image.resize(size, Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True)
            return output.getvalue()

    def _parse_page(
        self,
        content: str,
        path: Path,
        file_hash: str,
        page: int,
        existing_table_count: int,
    ) -> tuple[list[ParsedValue], list[ParsedTable]]:
        html_tables = re.findall(r"<table\b.*?</table>", content, flags=re.IGNORECASE | re.DOTALL)
        tables: list[ParsedTable] = []
        for html in html_tables:
            rows = self._html_rows(html)
            table = self._to_table(rows, path, file_hash, page, existing_table_count + len(tables) + 1)
            if table.values:
                tables.append(table)
        prose = re.sub(r"<table\b.*?</table>", "\n", content, flags=re.IGNORECASE | re.DOTALL)
        prose, markdown_tables = self._extract_markdown_tables(prose)
        for rows in markdown_tables:
            table = self._to_table(rows, path, file_hash, page, existing_table_count + len(tables) + 1)
            if table.values:
                tables.append(table)
        prose = unescape(re.sub(r"<[^>]+>", " ", prose))
        blocks = []
        for raw in re.split(r"\n\s*\n", prose):
            text = clean_text(raw)
            if text:
                blocks.append(ParsedValue(
                    raw_value=text,
                    confidence=self.default_confidence,
                    confidence_basis="SiliconFlow PaddleOCR-VL-1.5 response; configured uncalibrated confidence",
                    source=SourceRef(file_hash, path.name, page=page, bbox=(0.0, 0.0, 1000.0, 1000.0)),
                ))
        return blocks, tables

    def _to_table(self, rows: list[list[str]], path: Path, file_hash: str, page: int, table_index: int) -> ParsedTable:
        table = ParsedTable(name=f"page-{page}-table-{table_index}")
        for row_index, row in enumerate(rows, start=1):
            for column_index, raw_value in enumerate(row, start=1):
                text = clean_text(raw_value)
                if not text:
                    continue
                table.values.append(ParsedValue(
                    raw_value=text,
                    confidence=self.default_confidence,
                    confidence_basis="SiliconFlow PaddleOCR-VL-1.5 table; configured uncalibrated confidence",
                    source=SourceRef(
                        file_hash, path.name, page=page, bbox=(0.0, 0.0, 1000.0, 1000.0),
                        table=table_index, row=row_index, column=column_index,
                    ),
                ))
        return table

    @staticmethod
    def _html_rows(html: str) -> list[list[str]]:
        parser = _TableHTMLParser()
        parser.feed(unescape(html))
        parser.close()
        width = max((len(row) for row in parser.rows), default=0)
        return [row + [""] * (width - len(row)) for row in parser.rows] if width else []

    @staticmethod
    def _extract_markdown_tables(content: str) -> tuple[str, list[list[list[str]]]]:
        lines = content.splitlines()
        consumed: set[int] = set()
        tables: list[list[list[str]]] = []
        index = 0
        while index + 1 < len(lines):
            header = lines[index]
            separator = lines[index + 1]
            separator_cells = [cell.strip() for cell in separator.strip().strip("|").split("|")]
            if "|" not in header or not separator_cells or not all(
                re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in separator_cells
            ):
                index += 1
                continue
            end = index + 2
            while end < len(lines) and "|" in lines[end] and lines[end].strip():
                end += 1
            table_lines = [lines[index], *lines[index + 2 : end]]
            rows = [[clean_text(cell) for cell in line.strip().strip("|").split("|")] for line in table_lines]
            tables.append(rows)
            consumed.update(range(index, end))
            index = end
        prose = "\n".join(line for line_index, line in enumerate(lines) if line_index not in consumed)
        return prose, tables

    @staticmethod
    def _retry_after(response: httpx.Response | None) -> float | None:
        if response is None:
            return None
        value = response.headers.get("Retry-After")
        try:
            return min(float(value), 30.0) if value is not None else None
        except ValueError:
            return None
