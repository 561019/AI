from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FunctionRegistryEntry(BaseModel):
    engine_code: str
    engine_name: str
    supported_intents: list[str]
    supported_tasks: list[str]
    required_inputs: list[str] = Field(default_factory=list)
    description: str = ""
    legacy_function_codes: list[str] = Field(default_factory=list)


DEFAULT_REGISTRY_ENTRIES: tuple[FunctionRegistryEntry, ...] = (
    FunctionRegistryEntry(
        engine_code="ENG_DOCUMENT_TABLE_PARSING",
        engine_name="文档表格解析引擎",
        supported_intents=["数据查询型", "数据分析型"],
        supported_tasks=["DOCUMENT_TABLE_PARSE", "FILE_STRUCTURE_EXTRACT"],
        required_inputs=["file"],
        description="解析文档、表格、附件结构，只输出待解析任务。",
    ),
    FunctionRegistryEntry(
        engine_code="ENG_EXTERNAL_SYSTEM_CONNECTOR",
        engine_name="外部系统对接引擎",
        supported_intents=["数据查询型", "外部系统操作型"],
        supported_tasks=["EXTERNAL_DATA_FETCH", "EXTERNAL_SYSTEM_SUBMIT"],
        required_inputs=["external_system", "operation"],
        description="识别需要对接外部业务系统的数据获取或提交类任务。",
    ),
    FunctionRegistryEntry(
        engine_code="ENG_DATA_COLLECTION_AGGREGATION",
        engine_name="数据归集聚合引擎",
        supported_intents=["数据查询型", "数据分析型"],
        supported_tasks=[
            "DATA_QUERY_FETCH",
            "DATA_AGGREGATION_SUMMARY",
            "DATA_ANALYSIS_GROUP_SUM",
            "DATA_ANALYSIS_PIVOT",
            "DATA_FILTER",
            "DATA_SORT",
            "COMPLAINT_INFORMATION_ORGANIZE",
        ],
        required_inputs=["data_source", "operation"],
        description="处理数据获取、筛选、排序、汇总、透视和结构化整理任务。",
        legacy_function_codes=["FUNC_DATA_PROCESSING"],
    ),
    FunctionRegistryEntry(
        engine_code="ENG_RULE_CALCULATION",
        engine_name="规则计算引擎",
        supported_intents=["规则计算型"],
        supported_tasks=["RULE_CALCULATION_GENERAL", "RULE_CALCULATION_COMMISSION"],
        required_inputs=["calculation_policy", "calculation_basis"],
        description="识别基于明确规则、政策或公式的计算任务。",
    ),
    FunctionRegistryEntry(
        engine_code="ENG_ANALYTICS_FORECASTING",
        engine_name="分析预测引擎",
        supported_intents=["数据分析型"],
        supported_tasks=["DATA_ANALYSIS_PROBLEM", "DATA_ANALYSIS_YOY", "DATA_ANALYSIS_MOM", "DATA_ANALYSIS_FORECAST"],
        required_inputs=["analysis_object", "analysis_method"],
        description="识别问题分析、趋势分析、同比、环比和预测任务。",
    ),
    FunctionRegistryEntry(
        engine_code="ENG_KNOWLEDGE_QA",
        engine_name="知识库问答引擎",
        supported_intents=["智能问答型"],
        supported_tasks=["QUESTION_ANSWER"],
        required_inputs=["question"],
        description="处理简单单次知识问答任务。",
        legacy_function_codes=["FUNC_INTELLIGENT_QA"],
    ),
    FunctionRegistryEntry(
        engine_code="ENG_CONTENT_OUTPUT",
        engine_name="内容产出引擎",
        supported_intents=["文档生成型", "内容生成型"],
        supported_tasks=["DOCUMENT_GENERATE", "CONTENT_GENERATE", "IMPROVEMENT_PLAN_GENERATE"],
        required_inputs=["topic", "content_type"],
        description="识别报告、说明、方案、文案等文本内容生成任务。",
        legacy_function_codes=["FUNC_REPORT_GENERATION", "FUNC_CONTENT_CREATION"],
    ),
    FunctionRegistryEntry(
        engine_code="ENG_MULTIMEDIA_GENERATION",
        engine_name="多媒体生成引擎",
        supported_intents=["内容生成型"],
        supported_tasks=["MULTIMEDIA_GENERATE"],
        required_inputs=["media_type", "topic"],
        description="识别图片、音视频等多媒体生成任务。",
    ),
    FunctionRegistryEntry(
        engine_code="ENG_WORKFLOW_EXECUTION",
        engine_name="流程执行引擎",
        supported_intents=["流程办理型"],
        supported_tasks=["PROCESS_HANDLE", "WORKFLOW_START"],
        required_inputs=["process_name", "initiator"],
        description="识别流程办理类任务，仅输出结构化任务，不执行或编排流程。",
    ),
    FunctionRegistryEntry(
        engine_code="ENG_MONITORING_REMINDER",
        engine_name="监控提醒引擎",
        supported_intents=["流程办理型"],
        supported_tasks=["MONITORING_REMINDER"],
        required_inputs=["monitoring_object", "trigger_condition"],
        description="识别监控、预警、提醒类任务，仅输出结构化任务，不启动提醒。",
    ),
    FunctionRegistryEntry(
        engine_code="ENG_DIGITAL_ASSET",
        engine_name="数字资产引擎",
        supported_intents=["外部系统操作型", "文档生成型"],
        supported_tasks=["DIGITAL_ASSET_ACCRUAL_VOUCHER"],
        required_inputs=["asset_type", "source_result"],
        description="识别凭证、单据等数字资产类任务，仅输出结构化任务，不创建资产。",
    ),
)


class FunctionRegistryCatalog:
    """Read-only task-type registry used by the intent analysis layer.

    The intent analysis engine uses this catalog only to validate task_type,
    task descriptions, and required_inputs.  It must not be treated as an
    executable business-engine routing table.
    """

    def __init__(self, entries: list[FunctionRegistryEntry] | None = None) -> None:
        self.entries = entries or list(DEFAULT_REGISTRY_ENTRIES)
        self._by_engine_code = {entry.engine_code: entry for entry in self.entries}
        self._by_task: dict[str, FunctionRegistryEntry] = {}
        self._by_legacy_code: dict[str, FunctionRegistryEntry] = {}

        for entry in self.entries:
            for task_type in entry.supported_tasks:
                self._by_task.setdefault(task_type, entry)
            for function_code in entry.legacy_function_codes:
                self._by_legacy_code.setdefault(function_code, entry)

    @classmethod
    def from_database_functions(cls, functions: list[Any]) -> "FunctionRegistryCatalog":
        entries = list(DEFAULT_REGISTRY_ENTRIES)
        by_code = {entry.engine_code: entry for entry in entries}

        for function in functions:
            converted = cls._convert_database_function(function)
            if converted is None:
                continue
            by_code[converted.engine_code] = converted

        return cls(list(by_code.values()))

    @staticmethod
    def _convert_database_function(function: Any) -> FunctionRegistryEntry | None:
        function_code = str(getattr(function, "function_code", "") or "")
        if not function_code.startswith("ENG_"):
            return None

        metadata = getattr(function, "required_parameters", None)
        if not isinstance(metadata, dict):
            metadata = {}

        return FunctionRegistryEntry(
            engine_code=function_code,
            engine_name=str(getattr(function, "function_name", "") or function_code),
            supported_intents=[str(item) for item in metadata.get("supported_intents", [])],
            supported_tasks=[str(item) for item in metadata.get("supported_tasks", [])],
            required_inputs=[str(item) for item in metadata.get("required_inputs", [])],
            description=str(getattr(function, "description", "") or ""),
            legacy_function_codes=[str(item) for item in metadata.get("legacy_function_codes", [])],
        )

    def get_by_task_type(self, task_type: str) -> FunctionRegistryEntry:
        try:
            return self._by_task[task_type]
        except KeyError as error:
            raise KeyError(f"Task type is not registered: {task_type}") from error

    def get_by_engine_code(self, engine_code: str) -> FunctionRegistryEntry:
        try:
            return self._by_engine_code[engine_code]
        except KeyError as error:
            raise KeyError(f"Engine code is not registered: {engine_code}") from error

    def resolve_legacy_function(self, function_code: str) -> FunctionRegistryEntry | None:
        return self._by_legacy_code.get(function_code)

    def supported_intent_categories(self) -> list[str]:
        categories: list[str] = []
        for entry in self.entries:
            for category in entry.supported_intents:
                if category not in categories:
                    categories.append(category)
        return categories
