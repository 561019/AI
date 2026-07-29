from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field


class CoverageSegment(BaseModel):
    index: int
    text: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class MatchedTaskBinding(BaseModel):
    task_id: str
    task_type: str
    task_description: str = ""
    segment_index: int
    segment_text: str
    source: str


class PartialCoverageResult(BaseModel):
    coverage_rate: float = Field(ge=0, le=1)
    covered_segments: list[CoverageSegment] = Field(default_factory=list)
    uncovered_segments: list[CoverageSegment] = Field(default_factory=list)
    need_llm: bool = False


class PartialCoverageDetector:
    """Detects task coverage by binding matched tasks to source segments."""

    _SPLIT_RE = re.compile(r"(?:\s*[，,。；;！？!?]\s*|\s*(?:然后|接着|随后|最后|并且|并)\s*)")

    def segment(self, original_text: str) -> list[CoverageSegment]:
        text = original_text.strip()
        if not text:
            return []

        segments: list[CoverageSegment] = []
        cursor = 0
        for match in self._SPLIT_RE.finditer(text):
            self._append_segment(segments, text, cursor, match.start())
            cursor = match.end()
        self._append_segment(segments, text, cursor, len(text))

        return segments or [CoverageSegment(index=0, text=text, start=0, end=len(text))]

    def detect(
        self,
        *,
        original_text: str,
        segments: list[CoverageSegment],
        matched_tasks: list[MatchedTaskBinding],
    ) -> PartialCoverageResult:
        if not segments:
            return PartialCoverageResult(coverage_rate=0.0, need_llm=bool(original_text.strip()))

        covered_indexes = {
            task.segment_index
            for task in matched_tasks
            if self._is_valid_binding(task, segments)
        }
        covered = [segment for segment in segments if segment.index in covered_indexes]
        uncovered = [segment for segment in segments if segment.index not in covered_indexes]
        coverage_rate = len(covered) / len(segments)
        return PartialCoverageResult(
            coverage_rate=coverage_rate,
            covered_segments=covered,
            uncovered_segments=uncovered,
            need_llm=bool(uncovered),
        )

    def debug_payload(
        self,
        *,
        result: PartialCoverageResult | None,
        l1_tasks: list[dict[str, Any]],
        l2_tasks: list[dict[str, Any]],
        llm_called: bool,
        l3_compensation_success: bool,
    ) -> dict[str, Any]:
        return {
            "l1_tasks": l1_tasks,
            "l2_tasks": l2_tasks,
            "coverage_rate": result.coverage_rate if result is not None else 0.0,
            "covered_segments": [
                segment.model_dump(mode="json")
                for segment in (result.covered_segments if result is not None else [])
            ],
            "uncovered_segments": [
                segment.model_dump(mode="json")
                for segment in (result.uncovered_segments if result is not None else [])
            ],
            "need_llm": result.need_llm if result is not None else False,
            "llm_called": llm_called,
            "uncovered_segment_count": len(result.uncovered_segments) if result is not None else 0,
            "l3_compensation_success": l3_compensation_success,
        }

    def _append_segment(
        self,
        segments: list[CoverageSegment],
        source: str,
        start: int,
        end: int,
    ) -> None:
        raw = source[start:end]
        stripped = raw.strip()
        if not stripped:
            return
        local_start = start + raw.find(stripped)
        segments.append(
            CoverageSegment(
                index=len(segments),
                text=stripped,
                start=local_start,
                end=local_start + len(stripped),
            )
        )

    def _is_valid_binding(
        self,
        task: MatchedTaskBinding,
        segments: list[CoverageSegment],
    ) -> bool:
        if task.segment_index < 0 or task.segment_index >= len(segments):
            return False
        segment = segments[task.segment_index]
        return task.segment_text == segment.text
