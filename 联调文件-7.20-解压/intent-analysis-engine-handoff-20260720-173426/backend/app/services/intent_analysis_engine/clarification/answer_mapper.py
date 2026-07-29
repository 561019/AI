from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AnswerMapping:
    required_inputs: list[str]
    final_inputs: dict[str, str]
    mapped_inputs: dict[str, str]


class ClarificationAnswerMapper:
    """Maps a user's clarification answer to missing task inputs."""

    _SYSTEMS = ("ERP", "CRM", "OA", "SAP", "财务系统", "销售系统", "业务系统")
    _REGIONS = ("华东", "华南", "华北", "华中", "西南", "西北", "东北")

    def map_answer(self, *, answer: str, missing_inputs: list[str]) -> AnswerMapping:
        text = answer.strip()
        mapped: dict[str, str] = {}

        for input_name in missing_inputs:
            value = self._extract_value(input_name, text)
            if value:
                mapped[input_name] = value

        return AnswerMapping(
            required_inputs=[
                f"{input_name}:{value}"
                for input_name, value in mapped.items()
            ],
            final_inputs=self._final_inputs(mapped),
            mapped_inputs=mapped,
        )

    def _extract_value(self, input_name: str, text: str) -> str | None:
        if input_name == "calculation_policy":
            return self._extract_policy(text)
        if input_name in {"sales_data_source", "data_source"}:
            return self._extract_system(text)
        if input_name == "statistical_range":
            return self._extract_scope_or_time(text)
        if input_name == "classification_field":
            return self._extract_classification_field(text)
        if input_name == "summary_field":
            return self._extract_summary_field(text)
        if input_name == "analysis_object":
            return self._extract_after_marker(text, ["分析", "对象是", "看"])
        if input_name == "analysis_method":
            return self._extract_analysis_method(text)
        if input_name == "content_type":
            return self._extract_content_type(text)
        if input_name == "topic":
            return self._extract_topic(text)
        if input_name == "trigger_condition":
            return text if self._looks_like_trigger(text) else None
        if input_name == "monitoring_object":
            return self._extract_after_marker(text, ["监控", "提醒"])
        if input_name == "process_name":
            return self._extract_process_name(text)
        if input_name == "external_system":
            return self._extract_system(text)
        if input_name == "operation":
            return self._extract_operation(text)
        if input_name == "file":
            return self._extract_file_hint(text)
        return None

    def _extract_policy(self, text: str) -> str | None:
        patterns = [
            r"使用([^，,。；;\s]*(?:规则|政策))",
            r"根据([^，,。；;\s]*(?:规则|政策))",
            r"([^，,。；;\s]*(?:提成)?(?:规则|政策))",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return None

    def _extract_system(self, text: str) -> str | None:
        for system in self._SYSTEMS:
            if system.lower() in text.lower():
                return system.upper() if system.isascii() else system
        return None

    def _extract_scope_or_time(self, text: str) -> str | None:
        time_match = re.search(
            r"(20\d{2}年(?:\d{1,2}月)?|本月|上月|上个月|本季度|上季度|今年|去年|近\d+天|最近\d+天)",
            text,
        )
        if time_match:
            return time_match.group(1)
        for region in self._REGIONS:
            if region in text:
                return f"{region}区域"
        scope_match = re.search(r"([\u4e00-\u9fa5A-Za-z0-9]+区域)", text)
        return scope_match.group(1) if scope_match else None

    def _extract_classification_field(self, text: str) -> str | None:
        for field in ("区域", "产品", "客户", "部门", "渠道", "人员"):
            if field in text:
                return field
        return None

    def _extract_summary_field(self, text: str) -> str | None:
        for field in ("金额", "数量", "利润", "销售额", "收入", "成本", "提成"):
            if field in text:
                return field
        return None

    def _extract_analysis_method(self, text: str) -> str | None:
        for method in ("同比", "环比", "原因分析", "趋势分析", "预测", "异常分析"):
            if method in text:
                return method
        return None

    def _extract_content_type(self, text: str) -> str | None:
        for content_type in ("报告", "报表", "PPT", "文档", "通知", "邮件", "方案", "材料"):
            if content_type in text:
                return content_type
        return None

    def _extract_topic(self, text: str) -> str | None:
        topic_match = re.search(r"(?:主题|关于|围绕|生成)([^，,。；;]{1,20})", text)
        if topic_match:
            return topic_match.group(1).strip()
        return None

    def _looks_like_trigger(self, text: str) -> bool:
        return bool(
            re.search(r"(超过|低于|少于|高于|大于|小于|到期|逾期|每天|每周|每月|\d+)", text)
        )

    def _extract_process_name(self, text: str) -> str | None:
        for process in ("报销", "采购", "请假", "立项", "付款", "审批", "工单"):
            if process in text:
                return process
        return None

    def _extract_operation(self, text: str) -> str | None:
        for operation in ("获取", "查询", "拉取", "提交", "同步", "写入", "更新", "导出"):
            if operation in text:
                return operation
        return None

    def _extract_file_hint(self, text: str) -> str | None:
        for file_hint in ("附件", "文件", "Excel", "PDF", "Word", "表格"):
            if file_hint.lower() in text.lower():
                return file_hint
        return None

    def _extract_after_marker(self, text: str, markers: list[str]) -> str | None:
        for marker in markers:
            if marker in text:
                value = text.split(marker, 1)[1].strip(" ，,。；;")
                return value or None
        return None

    def _final_inputs(self, mapped: dict[str, str]) -> dict[str, str]:
        final_inputs: dict[str, str] = {}
        for input_name, value in mapped.items():
            output_name = input_name
            if input_name == "sales_data_source":
                output_name = "data_source"
            elif input_name == "statistical_range" and "区域" in value:
                output_name = "data_scope"
            final_inputs[output_name] = value
        return final_inputs
