from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from app.schemas.intent_analysis import IntentAnalysisResult
from app.services.context_provider import ContextInput
from app.services.intent_analysis_engine.conflict.rules import CLARIFICATION_QUESTIONS
from app.services.intent_analysis_engine.conflict.schemas import (
    ConflictDetectionResult,
    ConflictRecord,
    ConflictSource,
    ContextSignal,
)


class ConflictDetector:
    """Detects enterprise context conflicts without owning context storage."""

    DATA_SOURCE_PATTERNS: tuple[tuple[str, str], ...] = (
        (r"(?<![A-Za-z])ERP(?![A-Za-z])|ERP系统|企业资源计划", "ERP"),
        (r"(?<![A-Za-z])CRM(?![A-Za-z])|CRM系统|客户关系系统", "CRM"),
        (r"(?<![A-Za-z])OA(?![A-Za-z])|OA系统|办公系统", "OA"),
        (r"(?<![A-Za-z])SAP(?![A-Za-z])|SAP系统", "SAP"),
        (r"财务系统", "财务系统"),
        (r"销售系统", "销售系统"),
        (r"业务系统", "业务系统"),
        (r"数据仓库|数仓", "数据仓库"),
        (r"Excel|EXCEL|表格|电子表格", "Excel"),
    )
    STATISTICAL_DEFINITION_PATTERNS: tuple[tuple[str, str], ...] = (
        (r"回款金额|回款额|实收金额", "回款金额"),
        (r"订单金额|订单额", "订单金额"),
        (r"销售金额|销售额", "销售额"),
        (r"合同金额|合同额", "合同金额"),
        (r"开票金额|开票额", "开票金额"),
        (r"收入", "收入"),
        (r"毛利", "毛利"),
        (r"利润", "利润"),
    )
    TIME_RANGE_PATTERNS: tuple[tuple[str, str], ...] = (
        (r"(20\d{2})\s*年", "{0}年"),
        (r"(20\d{2})", "{0}年"),
        (r"今年|本年度|本年", "今年"),
        (r"去年|上一年|上年度", "去年"),
        (r"本月|这个月", "本月"),
        (r"上月|上个月", "上月"),
        (r"本季度|这个季度", "本季度"),
        (r"上季度|上一季度", "上季度"),
        (r"近三个月|最近三个月", "近三个月"),
    )

    def detect(
        self,
        *,
        current_input: str,
        context: ContextInput,
        result: IntentAnalysisResult,
    ) -> ConflictDetectionResult:
        if not result.tasks:
            return ConflictDetectionResult()

        task_id = result.tasks[0].task_id
        signals = [
            *self._signals_for_text(current_input, source="current_input"),
            *self._signals_for_context(context),
        ]
        conflicts = [
            *self._project_user_context_conflicts(signals, task_id=task_id),
            *self._field_conflicts(
                signals,
                task_id=task_id,
                field="data_source",
                conflict_type="DATA_SOURCE_CONFLICT",
                blocking=True,
                include_project_history_pair=False,
            ),
            *self._field_conflicts(
                signals,
                task_id=task_id,
                field="time_range",
                conflict_type="TIME_RANGE_CONFLICT",
                blocking=True,
            ),
            *self._field_conflicts(
                signals,
                task_id=task_id,
                field="statistical_definition",
                conflict_type="STATISTICAL_DEFINITION_CONFLICT",
                blocking=True,
            ),
            *self._current_context_conflicts(
                current_input=current_input,
                context=context,
                result=result,
            ),
        ]
        return ConflictDetectionResult(conflicts=self._deduplicate(conflicts))

    def _signals_for_text(self, text: str, *, source: ConflictSource) -> list[ContextSignal]:
        return [
            *self._pattern_signals(
                text,
                source=source,
                field="data_source",
                patterns=self.DATA_SOURCE_PATTERNS,
            ),
            *self._time_range_signals(text, source=source),
            *self._pattern_signals(
                text,
                source=source,
                field="statistical_definition",
                patterns=self.STATISTICAL_DEFINITION_PATTERNS,
            ),
            *self._task_focus_signals(text, source=source),
        ]

    def _signals_for_context(self, context: ContextInput) -> list[ContextSignal]:
        signals: list[ContextSignal] = []
        for source, scope in (
            ("conversation_context", context.current_conversation),
            ("project_context", context.current_project),
            ("historical_projects", context.historical_projects),
        ):
            items = scope.get("items")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                signals.extend(self._signals_for_context_item(item, source=source))
        return signals

    def _signals_for_context_item(self, item: dict[str, Any], *, source: ConflictSource) -> list[ContextSignal]:
        field_signals: list[ContextSignal] = []
        explicit_fields = {
            "data_source": ("data_source", "sales_data_source", "source_system", "system"),
            "time_range": ("time_range", "date_range", "period", "statistical_range"),
            "statistical_definition": (
                "statistical_definition",
                "statistical口径",
                "metric",
                "summary_field",
                "calculation_basis",
            ),
        }
        for field, keys in explicit_fields.items():
            for key in keys:
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    field_signals.append(
                        ContextSignal(
                            field=field,
                            value=self._normalize_value(field, value),
                            source=source,
                            raw_text=value,
                            explicit=True,
                        )
                    )
                    break

        for value in item.get("required_inputs", []) if isinstance(item.get("required_inputs"), list) else []:
            if not isinstance(value, str) or ":" not in value:
                continue
            key, raw_value = value.split(":", 1)
            key = key.strip()
            raw_value = raw_value.strip()
            if key in {"data_source", "sales_data_source"}:
                field_signals.append(
                    ContextSignal(
                        field="data_source",
                        value=self._normalize_value("data_source", raw_value),
                        source=source,
                        raw_text=value,
                        explicit=True,
                    )
                )
            elif key in {"time_range", "date_range", "period", "statistical_range"}:
                field_signals.append(
                    ContextSignal(
                        field="time_range",
                        value=self._normalize_value("time_range", raw_value),
                        source=source,
                        raw_text=value,
                        explicit=True,
                    )
                )
            elif key in {"statistical_definition", "metric", "summary_field", "calculation_basis"}:
                field_signals.append(
                    ContextSignal(
                        field="statistical_definition",
                        value=self._normalize_value("statistical_definition", raw_value),
                        source=source,
                        raw_text=value,
                        explicit=True,
                    )
                )

        context_text = self._context_item_text(item)
        return [
            *field_signals,
            *self._signals_for_text(context_text, source=source),
        ]

    def _pattern_signals(
        self,
        text: str,
        *,
        source: ConflictSource,
        field: str,
        patterns: Iterable[tuple[str, str]],
    ) -> list[ContextSignal]:
        signals: list[ContextSignal] = []
        for pattern, value in patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                signal = ContextSignal(
                    field=field,
                    value=value,
                    source=source,
                    raw_text=text,
                    explicit=self._is_explicit_signal(field, text, value),
                )
                if signal.value not in {item.value for item in signals}:
                    signals.append(signal)
        return signals

    def _time_range_signals(self, text: str, *, source: ConflictSource) -> list[ContextSignal]:
        signals: list[ContextSignal] = []
        for pattern, template in self.TIME_RANGE_PATTERNS:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                value = template.format(match.group(1)) if match.groups() else template
                if value not in {item.value for item in signals}:
                    signals.append(
                        ContextSignal(
                            field="time_range",
                            value=value,
                            source=source,
                            raw_text=text,
                            explicit=True,
                        )
                    )
        return signals

    def _task_focus_signals(self, text: str, *, source: ConflictSource) -> list[ContextSignal]:
        values: list[str] = []
        if re.search(r"DOCUMENT_GENERATE|报告|报表|文档|材料|PPT|生成销售分析报告", text, flags=re.IGNORECASE):
            values.append("report_generation")
        if re.search(r"DATA_ANALYSIS|分析|原因|下降|趋势", text, flags=re.IGNORECASE):
            values.append("analysis")
        if re.search(r"DATA_QUERY_FETCH|整理|获取|查询|拉取|销售数据", text, flags=re.IGNORECASE):
            values.append("data_preparation")
        return [
            ContextSignal(field="task_focus", value=value, source=source, raw_text=text)
            for value in dict.fromkeys(values)
        ]

    def _field_conflicts(
        self,
        signals: list[ContextSignal],
        *,
        task_id: str,
        field: str,
        conflict_type: str,
        blocking: bool,
        include_project_history_pair: bool = True,
    ) -> list[ConflictRecord]:
        relevant = [signal for signal in signals if signal.field == field]
        conflicts: list[ConflictRecord] = []
        for left_index, left in enumerate(relevant):
            for right in relevant[left_index + 1 :]:
                if left.source == right.source or left.value == right.value:
                    continue
                if field == "statistical_definition" and not (left.explicit and right.explicit):
                    continue
                if (
                    not include_project_history_pair
                    and {left.source, right.source} == {"project_context", "historical_projects"}
                ):
                    continue
                if (
                    field == "data_source"
                    and "current_input" not in {left.source, right.source}
                    and "conversation_context" not in {left.source, right.source}
                ):
                    continue
                conflicts.append(
                    ConflictRecord(
                        task_id=task_id,
                        conflict_type=conflict_type,  # type: ignore[arg-type]
                        severity="blocking" if blocking else "warning",
                        description=f"{field} conflict: {left.value} vs {right.value}",
                        left_value=left.value,
                        right_value=right.value,
                        source_left=left.source,
                        source_right=right.source,
                        resolution_status="needs_clarification" if blocking else "recorded",
                        clarification_question=CLARIFICATION_QUESTIONS[conflict_type],  # type: ignore[index]
                    )
                )
        return conflicts

    def _project_user_context_conflicts(
        self,
        signals: list[ContextSignal],
        *,
        task_id: str,
    ) -> list[ConflictRecord]:
        project_sources = [
            signal
            for signal in signals
            if signal.field == "data_source" and signal.source == "project_context"
        ]
        history_sources = [
            signal
            for signal in signals
            if signal.field == "data_source" and signal.source == "historical_projects"
        ]
        conflicts: list[ConflictRecord] = []
        for project in project_sources:
            for history in history_sources:
                if project.value == history.value:
                    continue
                conflicts.append(
                    ConflictRecord(
                        task_id=task_id,
                        conflict_type="PROJECT_USER_CONTEXT_CONFLICT",
                        severity="warning",
                        description=f"Project context data source {project.value} overrides historical project source {history.value}.",
                        left_value=project.value,
                        right_value=history.value,
                        source_left="project_context",
                        source_right="historical_projects",
                        resolution_status="resolved",
                        clarification_question=None,
                    )
                )
        return conflicts

    def _current_context_conflicts(
        self,
        *,
        current_input: str,
        context: ContextInput,
        result: IntentAnalysisResult,
    ) -> list[ConflictRecord]:
        if not result.tasks:
            return []
        current_focus = self._primary_task_focus(current_input)
        if current_focus is None:
            return []
        context_focus = self._nearest_context_focus(context)
        if context_focus is None or context_focus == current_focus:
            return []
        return [
            ConflictRecord(
                task_id=result.tasks[0].task_id,
                conflict_type="CURRENT_CONTEXT_CONFLICT",
                severity="warning",
                description=f"Current input focus {current_focus} overrides previous context focus {context_focus}.",
                left_value=current_focus,
                right_value=context_focus,
                source_left="current_input",
                source_right="conversation_context",
                resolution_status="recorded",
                clarification_question=None,
            )
        ]

    def _primary_task_focus(self, text: str) -> str | None:
        signals = self._task_focus_signals(text, source="current_input")
        if not signals:
            return None
        if any(signal.value == "data_preparation" for signal in signals):
            return "data_preparation"
        return signals[0].value

    def _nearest_context_focus(self, context: ContextInput) -> str | None:
        for source, scope in (
            ("conversation_context", context.current_conversation),
            ("project_context", context.current_project),
            ("historical_projects", context.historical_projects),
        ):
            items = scope.get("items")
            if not isinstance(items, list):
                continue
            for item in reversed(items):
                if not isinstance(item, dict):
                    continue
                signals = [
                    signal
                    for signal in self._signals_for_context_item(item, source=source)
                    if signal.field == "task_focus"
                ]
                if signals:
                    return signals[0].value
        return None

    def _context_item_text(self, item: dict[str, Any]) -> str:
        values: list[str] = []
        for key in (
            "task_type",
            "task_description",
            "task_name",
            "source_text",
            "normalized_text",
            "action",
            "object",
            "business_object",
            "text",
            "content",
        ):
            value = item.get(key)
            if isinstance(value, str) and value:
                values.append(value)
        return " ".join(values)

    def _normalize_value(self, field: str, value: str) -> str:
        text = value.strip()
        if field == "data_source":
            for pattern, normalized in self.DATA_SOURCE_PATTERNS:
                if re.search(pattern, text, flags=re.IGNORECASE):
                    return normalized
        if field == "statistical_definition":
            for pattern, normalized in self.STATISTICAL_DEFINITION_PATTERNS:
                if re.search(pattern, text, flags=re.IGNORECASE):
                    return normalized
        if field == "time_range":
            signals = self._time_range_signals(text, source="current_input")
            if signals:
                return signals[0].value
        return text

    def _is_explicit_signal(self, field: str, text: str, value: str) -> bool:
        if field in {"data_source", "time_range"}:
            return True
        if field != "statistical_definition":
            return False
        escaped = re.escape(value)
        return bool(
            re.search(rf"(?:按|以|基于|按照).{{0,12}}{escaped}", text)
            or re.search(rf"(?:统计口径|口径|指标|字段|维度).{{0,20}}{escaped}", text)
            or re.search(rf"{escaped}.{{0,8}}(?:口径|指标|字段)", text)
        )

    def _deduplicate(self, conflicts: list[ConflictRecord]) -> list[ConflictRecord]:
        unique: list[ConflictRecord] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for conflict in conflicts:
            value_pair = tuple(sorted((conflict.left_value, conflict.right_value)))
            source_pair = tuple(sorted((conflict.source_left, conflict.source_right)))
            key = (
                conflict.conflict_type,
                value_pair[0],
                value_pair[1],
                source_pair[0],
                source_pair[1],
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(conflict)
        return unique
