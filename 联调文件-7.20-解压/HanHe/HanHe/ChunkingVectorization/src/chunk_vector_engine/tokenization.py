from __future__ import annotations

import re


TOKEN_PATTERN = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9_]+|[^\s]", re.UNICODE)
SENTENCE_PATTERN = re.compile(r".+?(?:\n+|[。！？!?；;]+|$)", re.DOTALL)


class EstimatedTokenizer:
    """A deterministic conservative counter for mixed Chinese/Latin text.

    Chunk limits are far below Qwen3's context limit, so this avoids a runtime
    model-tokenizer download while still producing stable process artifacts.
    """

    def spans(self, text: str) -> list[tuple[int, int]]:
        return [match.span() for match in TOKEN_PATTERN.finditer(text)]

    def count(self, text: str) -> int:
        return len(self.spans(text))

    def tail(self, text: str, token_count: int) -> str:
        if token_count <= 0:
            return ""
        spans = self.spans(text)
        if len(spans) <= token_count:
            return text
        return text[spans[-token_count][0] :].strip()

    def hard_split(self, text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
        spans = self.spans(text)
        if len(spans) <= max_tokens:
            return [text.strip()] if text.strip() else []
        result: list[str] = []
        start_token = 0
        while start_token < len(spans):
            end_token = min(start_token + max_tokens, len(spans))
            start_char = 0 if start_token == 0 else spans[start_token][0]
            end_char = len(text) if end_token == len(spans) else spans[end_token - 1][1]
            piece = text[start_char:end_char].strip()
            if piece:
                result.append(piece)
            if end_token == len(spans):
                break
            start_token = max(start_token + 1, end_token - overlap_tokens)
        return result

    def split_text(self, text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
        text = text.strip()
        if not text or self.count(text) <= max_tokens:
            return [text] if text else []

        sentences = [match.group(0).strip() for match in SENTENCE_PATTERN.finditer(text) if match.group(0).strip()]
        pieces: list[str] = []
        current = ""
        for sentence in sentences:
            if self.count(sentence) > max_tokens:
                if current:
                    pieces.append(current)
                    current = ""
                pieces.extend(self.hard_split(sentence, max_tokens, overlap_tokens))
                continue
            candidate = f"{current}\n{sentence}".strip() if current else sentence
            if current and self.count(candidate) > max_tokens:
                pieces.append(current)
                overlap = self.tail(current, overlap_tokens)
                current = f"{overlap}\n{sentence}".strip() if overlap else sentence
                if self.count(current) > max_tokens:
                    pieces.extend(self.hard_split(current, max_tokens, overlap_tokens))
                    current = ""
            else:
                current = candidate
        if current:
            pieces.append(current)
        return pieces

