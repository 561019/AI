from __future__ import annotations

from app.services.intent_analysis_engine.conflict.schemas import ConflictSource, ConflictType


SOURCE_PRIORITY: dict[ConflictSource, int] = {
    "current_input": 4,
    "conversation_context": 3,
    "project_context": 2,
    "historical_projects": 1,
}

BLOCKING_CONFLICT_TYPES: set[ConflictType] = {
    "DATA_SOURCE_CONFLICT",
    "TIME_RANGE_CONFLICT",
    "STATISTICAL_DEFINITION_CONFLICT",
}

CONFLICT_MISSING_INPUT_PREFIX = "conflict"

CLARIFICATION_QUESTIONS: dict[ConflictType, str] = {
    "DATA_SOURCE_CONFLICT": "检测到多个明确数据源，请确认本次任务以哪个数据源为准。",
    "TIME_RANGE_CONFLICT": "检测到当前输入和上下文中的时间范围不同，请确认本次任务使用哪个时间范围。",
    "STATISTICAL_DEFINITION_CONFLICT": "检测到统计口径冲突，请确认本次任务使用哪个统计口径。",
    "CURRENT_CONTEXT_CONFLICT": "当前输入与历史任务不一致，已按当前输入处理。",
    "PROJECT_USER_CONTEXT_CONFLICT": "项目上下文与用户历史上下文的数据源不同，已按项目上下文处理。",
}


def conflict_missing_input(conflict_type: str) -> str:
    return f"{CONFLICT_MISSING_INPUT_PREFIX}:{conflict_type}"
