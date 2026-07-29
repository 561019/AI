from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NoiseFilterResult:
    filtered_text: str
    removed_fragments: list[str]


class NoiseFilter:
    """Removes conversational padding while retaining explicit business facts."""

    _PREFIX_PATTERNS = (
        r"^(?:你好|您好|请问)[，,。！？!?\s]*",
        r"^(?:麻烦|劳驾|辛苦)(?:你|您)?(?:帮我|帮忙)?[，,。！？!?\s]*",
        r"^(?:能不能|可以不可以|可不可以)(?:帮我|帮忙)?[，,。！？!?\s]*",
        r"^(?:我想|我希望|我需要|想要)(?:请你|让你)?[，,。！？!?\s]*",
    )
    _NOISE_CLAUSE_PATTERNS = (
        r"^(?:最近)?事情(?:比较|有点|特别)?多$",
        r"^我(?:最近)?(?:比较|非常|特别)?忙$",
        r"^(?:老板|领导)(?:一直)?催(?:得)?(?:比较|很|特别)?急$",
        r"^(?:这个事情|这件事)(?:比较|很)?着急$",
        r"^时间(?:比较|很)?紧$",
        r"^不好意思(?:打扰了)?$",
        r"^谢谢(?:了)?$",
    )

    def filter(self, text: str) -> NoiseFilterResult:
        cleaned = text.strip()
        removed: list[str] = []

        for pattern in self._PREFIX_PATTERNS:
            updated = re.sub(pattern, "", cleaned, count=1, flags=re.IGNORECASE)
            if updated != cleaned:
                removed.append(cleaned[: len(cleaned) - len(updated)].strip(" ，,。！？!?"))
                cleaned = updated.strip()

        clauses = [part.strip() for part in re.split(r"[，,。；;！!？?]+", cleaned) if part.strip()]
        kept: list[str] = []
        for clause in clauses:
            is_background = clause.startswith(("因为", "由于")) and any(
                marker in clause for marker in ("开会", "分析会", "汇报会", "会议")
            )
            if is_background or any(re.fullmatch(pattern, clause) for pattern in self._NOISE_CLAUSE_PATTERNS):
                removed.append(clause)
            else:
                kept.append(clause)

        return NoiseFilterResult(
            filtered_text="，".join(kept).strip(" ，,。；;！!？?"),
            removed_fragments=removed,
        )
