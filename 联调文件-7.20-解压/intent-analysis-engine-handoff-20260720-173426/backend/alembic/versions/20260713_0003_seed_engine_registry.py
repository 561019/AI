"""seed registered target engines

Revision ID: 20260713_0003
Revises: 20260713_0002
Create Date: 2026-07-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260713_0003"
down_revision: str | None = "20260713_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ENGINE_ROWS = (
    {
        "function_code": "ENG_DOCUMENT_TABLE_PARSING",
        "function_name": "文档表格解析引擎",
        "intent_category": "数据查询型",
        "target_engine": "文档表格解析引擎",
        "description": "Route document and spreadsheet parsing tasks.",
        "required_parameters": {"supported_intents": ["数据查询型", "数据分析型"], "supported_tasks": ["DOCUMENT_TABLE_PARSE", "FILE_STRUCTURE_EXTRACT"], "required_inputs": ["file"]},
        "example_sentences": ["解析这份Excel", "读取上传表格结构"],
    },
    {
        "function_code": "ENG_EXTERNAL_SYSTEM_CONNECTOR",
        "function_name": "外部系统对接引擎",
        "intent_category": "外部系统操作型",
        "target_engine": "外部系统对接引擎",
        "description": "Route external system fetch and submit tasks.",
        "required_parameters": {"supported_intents": ["数据查询型", "外部系统操作型"], "supported_tasks": ["EXTERNAL_DATA_FETCH", "EXTERNAL_SYSTEM_SUBMIT"], "required_inputs": ["external_system", "operation"]},
        "example_sentences": ["从CRM获取客户信息", "提交到财务系统"],
    },
    {
        "function_code": "ENG_DATA_COLLECTION_AGGREGATION",
        "function_name": "数据归集聚合引擎",
        "intent_category": "数据分析型",
        "target_engine": "数据归集聚合引擎",
        "description": "Route data fetch, aggregation, filtering, sorting, and pivot tasks.",
        "required_parameters": {"supported_intents": ["数据查询型", "数据分析型"], "supported_tasks": ["DATA_QUERY_FETCH", "DATA_AGGREGATION_SUMMARY", "DATA_ANALYSIS_GROUP_SUM", "DATA_ANALYSIS_PIVOT", "DATA_FILTER", "DATA_SORT", "COMPLAINT_INFORMATION_ORGANIZE"], "required_inputs": ["data_source", "operation"], "legacy_function_codes": ["FUNC_DATA_PROCESSING"]},
        "example_sentences": ["统计销售金额", "生成销售数据透视表"],
    },
    {
        "function_code": "ENG_RULE_CALCULATION",
        "function_name": "规则计算引擎",
        "intent_category": "规则计算型",
        "target_engine": "规则计算引擎",
        "description": "Route policy, rule, and formula based calculation tasks.",
        "required_parameters": {"supported_intents": ["规则计算型"], "supported_tasks": ["RULE_CALCULATION_GENERAL", "RULE_CALCULATION_COMMISSION"], "required_inputs": ["calculation_policy", "calculation_basis"]},
        "example_sentences": ["计算销售提成", "根据政策计算奖金"],
    },
    {
        "function_code": "ENG_ANALYTICS_FORECASTING",
        "function_name": "分析预测引擎",
        "intent_category": "数据分析型",
        "target_engine": "分析预测引擎",
        "description": "Route issue analysis, comparison, and forecast tasks.",
        "required_parameters": {"supported_intents": ["数据分析型"], "supported_tasks": ["DATA_ANALYSIS_PROBLEM", "DATA_ANALYSIS_YOY", "DATA_ANALYSIS_MOM", "DATA_ANALYSIS_FORECAST"], "required_inputs": ["analysis_object", "analysis_method"]},
        "example_sentences": ["分析客户投诉原因", "做同比分析"],
    },
    {
        "function_code": "ENG_KNOWLEDGE_QA",
        "function_name": "知识库问答引擎",
        "intent_category": "智能问答型",
        "target_engine": "知识库问答引擎",
        "description": "Route knowledge question answering tasks.",
        "required_parameters": {"supported_intents": ["智能问答型"], "supported_tasks": ["QUESTION_ANSWER"], "required_inputs": ["question"], "legacy_function_codes": ["FUNC_INTELLIGENT_QA"]},
        "example_sentences": ["公司的报销政策是什么？", "什么是销售政策？"],
    },
    {
        "function_code": "ENG_CONTENT_OUTPUT",
        "function_name": "内容产出引擎",
        "intent_category": "内容生成型",
        "target_engine": "内容产出引擎",
        "description": "Route report, document, explanation, and plan generation tasks.",
        "required_parameters": {"supported_intents": ["文档生成型", "内容生成型"], "supported_tasks": ["DOCUMENT_GENERATE", "CONTENT_GENERATE", "IMPROVEMENT_PLAN_GENERATE"], "required_inputs": ["topic", "content_type"], "legacy_function_codes": ["FUNC_REPORT_GENERATION", "FUNC_CONTENT_CREATION"]},
        "example_sentences": ["生成经营分析报告", "生成改进方案"],
    },
    {
        "function_code": "ENG_MULTIMEDIA_GENERATION",
        "function_name": "多媒体生成引擎",
        "intent_category": "内容生成型",
        "target_engine": "多媒体生成引擎",
        "description": "Route image, audio, and video generation tasks.",
        "required_parameters": {"supported_intents": ["内容生成型"], "supported_tasks": ["MULTIMEDIA_GENERATE"], "required_inputs": ["media_type", "topic"]},
        "example_sentences": ["生成宣传图片", "制作讲解视频"],
    },
    {
        "function_code": "ENG_WORKFLOW_EXECUTION",
        "function_name": "流程执行引擎",
        "intent_category": "流程办理型",
        "target_engine": "流程执行引擎",
        "description": "Route workflow initiation and process handling tasks.",
        "required_parameters": {"supported_intents": ["流程办理型"], "supported_tasks": ["PROCESS_HANDLE", "WORKFLOW_START"], "required_inputs": ["process_name", "initiator"]},
        "example_sentences": ["发起审批流程", "办理报销流程"],
    },
    {
        "function_code": "ENG_MONITORING_REMINDER",
        "function_name": "监控提醒引擎",
        "intent_category": "流程办理型",
        "target_engine": "监控提醒引擎",
        "description": "Route monitoring, alerting, and reminder tasks.",
        "required_parameters": {"supported_intents": ["流程办理型"], "supported_tasks": ["MONITORING_REMINDER"], "required_inputs": ["monitoring_object", "trigger_condition"]},
        "example_sentences": ["到期提醒我", "监控库存低于阈值"],
    },
    {
        "function_code": "ENG_DIGITAL_ASSET",
        "function_name": "数字资产引擎",
        "intent_category": "外部系统操作型",
        "target_engine": "数字资产引擎",
        "description": "Route voucher, document, and digital asset creation tasks.",
        "required_parameters": {"supported_intents": ["外部系统操作型", "文档生成型"], "supported_tasks": ["DIGITAL_ASSET_ACCRUAL_VOUCHER"], "required_inputs": ["asset_type", "source_result"]},
        "example_sentences": ["生成计提凭证", "创建业务单据"],
    },
)


def upgrade() -> None:
    registry = sa.table(
        "function_registry",
        sa.column("function_code", sa.String()),
        sa.column("function_name", sa.String()),
        sa.column("intent_category", sa.String()),
        sa.column("target_engine", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("required_parameters", postgresql.JSONB()),
        sa.column("example_sentences", postgresql.JSONB()),
        sa.column("status", sa.String()),
    )
    rows = [{**row, "status": "active"} for row in ENGINE_ROWS]
    statement = postgresql.insert(registry).values(rows).on_conflict_do_nothing(index_elements=["function_code"])
    op.execute(statement)


def downgrade() -> None:
    codes = [row["function_code"] for row in ENGINE_ROWS]
    op.execute(
        sa.text("DELETE FROM function_registry WHERE function_code = ANY(:codes)").bindparams(
            sa.bindparam("codes", value=codes, type_=postgresql.ARRAY(sa.String()))
        )
    )
