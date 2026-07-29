from __future__ import annotations

import re

from pydantic import BaseModel, Field


class ExtractedConversationContext(BaseModel):
    user_goal: str
    actions: list[str] = Field(default_factory=list)
    business_objects: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    time_ranges: list[str] = Field(default_factory=list)
    people_organizations: list[str] = Field(default_factory=list)
    data_scopes: list[str] = Field(default_factory=list)
    summary_fields: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    context_information: list[str] = Field(default_factory=list)


class ContextExtractor:
    """Extracts only facts explicitly present in the current request."""

    ACTION_PATTERNS = {
        "获取": ("查询", "获取", "拉取", "拉", "导出", "列出", "调出", "调出来", "拿出来", "拿出", "取出来", "取出", "整理出来"),
        "整理": ("整理", "汇总", "统计", "归集"),
        "计算": ("计算", "核算", "测算", "算一下", "算出"),
        "分析": ("分析", "判断", "评估", "看一下", "看看", "了解", "诊断", "找原因", "原因"),
        "生成": ("生成", "制作", "做一份", "弄一份", "写一份", "输出", "汇报"),
        "检查": ("检查", "有没有问题", "是否异常", "排查"),
        "提醒": ("提醒", "监控", "预警", "告警"),
    }
    BUSINESS_OBJECTS = (
        "销售数据",
        "销售情况",
        "销售额",
        "销量",
        "销售奖励",
        "销售",
        "桂中需求",
        "复购率",
        "需求",
        "经销商",
        "利润情况",
        "利润",
        "经营情况",
        "经营数据",
        "经营",
        "客户投诉",
        "客户信息",
        "客户",
        "渠道线索",
        "渠道",
        "线索",
        "会员续约",
        "续约",
        "退款金额",
        "退款数据",
        "退款明细",
        "退款",
        "门店",
        "会员",
        "供应商档案",
        "供应商资料",
        "供应商",
        "库存",
        "订单",
        "回款",
        "费用",
        "成本",
        "提成",
        "奖金",
        "凭证",
        "文件",
        "海报",
        "宣传图",
        "图片",
        "封面",
    )
    TIME_PATTERNS = (
        r"去年",
        r"今年",
        r"上个月",
        r"上月",
        r"本月",
        r"六月",
        r"下季度",
        r"最近(?:一|两|三|四|五|六|七|八|九|十|\d+)?(?:天|周|个月|季度|年)",
        r"第[一二三四1-4]季度",
        r"上季度",
        r"本季度",
        r"\d{1,2}月",
        r"\d{4}年(?:\d{1,2}月)?",
    )
    ORGANIZATIONS = ("华东区域", "华南区域", "华北区域", "西南区域", "桂中", "总部", "分公司", "销售部", "财务部", "领导", "管理层", "老板")
    DATA_SCOPES = ("各区域", "华东区域", "华南区域", "华北区域", "西南区域", "桂中", "全部", "所有", "前十名经销商", "经销商", "各部门", "各产品", "各渠道", "渠道", "城市", "会员等级", "销售人员", "门店", "等级", "分层")

    def extract(self, text: str, *, context_information: list[str] | None = None) -> ExtractedConversationContext:
        actions = [standard for standard, variants in self.ACTION_PATTERNS.items() if any(value in text for value in variants)]
        objects = self._ordered_matches(text, self.BUSINESS_OBJECTS)
        time_ranges = self._regex_matches(text, self.TIME_PATTERNS)
        organizations = self._ordered_matches(text, self.ORGANIZATIONS)
        data_scopes = self._ordered_matches(text, self.DATA_SCOPES)
        summary_fields = self._ordered_matches(
            text,
            ("复购率", "需求", "续约率", "退款金额", "销售额", "金额", "数量", "利润", "收入", "订单数", "业绩", "销量", "总额", "合计"),
        )
        data_sources = self._ordered_matches(
            text,
            ("Excel", "excel", "PDF", "pdf", "Word", "word", "附件", "文件", "CRM", "ERP", "OA", "SAP", "财务系统", "业务系统"),
        )
        constraints = self._constraints(text)

        goal_parts = actions + objects
        user_goal = "、".join(goal_parts) if goal_parts else text.strip()
        return ExtractedConversationContext(
            user_goal=user_goal,
            actions=actions,
            business_objects=objects,
            constraints=constraints,
            time_ranges=time_ranges,
            people_organizations=organizations,
            data_scopes=data_scopes,
            summary_fields=summary_fields,
            data_sources=data_sources,
            context_information=context_information or [],
        )

    def _ordered_matches(self, text: str, values: tuple[str, ...]) -> list[str]:
        matches = [(text.find(value), value) for value in values if value in text]
        result: list[str] = []
        for _, value in sorted(matches, key=lambda item: (item[0], -len(item[1]))):
            if value not in result and not any(value in existing for existing in result):
                result.append(value)
        return result

    def _regex_matches(self, text: str, patterns: tuple[str, ...]) -> list[str]:
        found: list[tuple[int, str]] = []
        for pattern in patterns:
            found.extend((match.start(), match.group(0)) for match in re.finditer(pattern, text))
        result: list[str] = []
        for _, value in sorted(found):
            if value not in result:
                result.append(value)
        return result

    def _constraints(self, text: str) -> list[str]:
        constraints: list[str] = []
        if "给领导看" in text or "领导看的" in text:
            constraints.append("受众:领导")
        if "管理层" in text:
            constraints.append("受众:管理层")
        if "PPT" in text.upper() or "幻灯片" in text:
            constraints.append("内容类型:PPT")
        if "按区域" in text or "各区域" in text:
            constraints.append("维度:区域")
        if "下降" in text:
            constraints.append("关注项:下降")
        return constraints
