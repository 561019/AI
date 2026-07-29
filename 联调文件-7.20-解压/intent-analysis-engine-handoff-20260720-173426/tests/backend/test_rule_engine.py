from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.models import FunctionRegistry, RuleMapping
from app.services.rule_engine import RuleEngineRepository, RuleMatcher


def make_rule(
    keyword: str,
    function_code: str,
    *,
    pattern: str | None = None,
    priority: int = 100,
    status: str = "active",
) -> RuleMapping:
    return RuleMapping(
        keyword=keyword,
        pattern=pattern,
        function_code=function_code,
        priority=priority,
        status=status,
        created_at=datetime.now(UTC),
    )


def make_function(
    function_code: str,
    intent_category: str,
    target_engine: str,
    *,
    status: str = "active",
) -> FunctionRegistry:
    return FunctionRegistry(
        function_code=function_code,
        function_name=function_code,
        intent_category=intent_category,
        target_engine=target_engine,
        description=f"{function_code} definition.",
        required_parameters={},
        example_sentences=[],
        status=status,
    )


class FakeRuleRepository:
    def __init__(self, rules: list[RuleMapping]) -> None:
        self.rules = rules

    def list_active_rules(self) -> list[RuleMapping]:
        return [rule for rule in self.rules if rule.status == "active"]


class FakeFunctionRegistryRepository:
    def __init__(self, functions: dict[str, FunctionRegistry]) -> None:
        self.functions = functions
        self.requested_codes: list[str] = []

    def get_by_code(self, function_code: str) -> FunctionRegistry | None:
        self.requested_codes.append(function_code)
        return self.functions.get(function_code)


def build_matcher(
    *,
    rules: list[RuleMapping] | None = None,
    functions: dict[str, FunctionRegistry] | None = None,
) -> RuleMatcher:
    rules = rules or [
        make_rule("生成报告", "REPORT_CREATE", pattern=r"生成.*报告", priority=10),
        make_rule("报告", "REPORT_GENERIC", pattern=r"报告", priority=50),
        make_rule("查询数据", "DATA_QUERY", pattern=r"(查询|查看).*(数据|销售|回款)", priority=20),
        make_rule("计算", "CALCULATION", pattern=r"(计算|算一下|核算)", priority=30),
        make_rule("汇总", "DATA_SUMMARY", pattern=r"(汇总|分类求和|合计)", priority=25),
        make_rule("经营情况总结", "REPORT_CREATE", pattern=r"(经营情况总结|经营总结|经营分析总结|做个.*总结)", priority=15),
    ]
    functions = functions or {
        "REPORT_CREATE": make_function("REPORT_CREATE", "报告生成型", "report_engine"),
        "REPORT_GENERIC": make_function("REPORT_GENERIC", "报告生成型", "report_engine"),
        "DATA_QUERY": make_function("DATA_QUERY", "智能问答型", "knowledge_qa_engine"),
        "CALCULATION": make_function("CALCULATION", "规则计算型", "rule_calculation_engine"),
        "DATA_SUMMARY": make_function("DATA_SUMMARY", "数据处理型", "data_aggregation_engine"),
    }
    return RuleMatcher(
        rule_repository=FakeRuleRepository(rules),
        function_registry_repository=FakeFunctionRegistryRepository(functions),
    )


@pytest.mark.parametrize(
    ("text", "expected_matched", "expected_function_code"),
    [
        ("生成报告", True, "REPORT_CREATE"),
        ("帮我生成报告", True, "REPORT_CREATE"),
        ("帮我生成一份销售分析报告", True, "REPORT_CREATE"),
        ("请生成月度经营报告", True, "REPORT_CREATE"),
        ("报告", True, "REPORT_GENERIC"),
        ("查询数据", True, "DATA_QUERY"),
        ("帮我查询数据", True, "DATA_QUERY"),
        ("查询一下上个月销售数据", True, "DATA_QUERY"),
        ("查看销售回款", True, "DATA_QUERY"),
        ("我要查看历史数据", True, "DATA_QUERY"),
        ("计算", True, "CALCULATION"),
        ("帮我计算一下提成", True, "CALCULATION"),
        ("算一下这个月提成", True, "CALCULATION"),
        ("核算销售提成", True, "CALCULATION"),
        ("汇总", True, "DATA_SUMMARY"),
        ("帮我汇总这张表", True, "DATA_SUMMARY"),
        ("按产品分类求和", True, "DATA_SUMMARY"),
        ("把销售额合计一下", True, "DATA_SUMMARY"),
        ("帮我做个经营情况总结", True, "REPORT_CREATE"),
        ("请做个经营总结", True, "REPORT_CREATE"),
        ("生成一份经营分析总结", True, "REPORT_CREATE"),
        ("今天天气怎么样", False, None),
        ("明天会下雨吗", False, None),
        ("讲个笑话", False, None),
        ("帮我订一杯咖啡", False, None),
        ("打开音乐", False, None),
        ("随便聊聊", False, None),
        ("", False, None),
        ("   ", False, None),
        ("未知业务请求", False, None),
    ],
)
def test_rule_matcher_covers_level_one_cases(
    text: str,
    expected_matched: bool,
    expected_function_code: str | None,
) -> None:
    result = build_matcher().match(text)

    assert result.level == 1
    assert result.matched is expected_matched
    assert result.function_code == expected_function_code


def test_exact_keyword_match_returns_full_confidence() -> None:
    result = build_matcher().match("生成报告")

    assert result.matched is True
    assert result.confidence == 1.0


def test_contained_keyword_match_returns_keyword_confidence() -> None:
    result = build_matcher().match("帮我生成报告")

    assert result.matched is True
    assert result.confidence == 0.95


def test_pattern_only_match_returns_pattern_confidence() -> None:
    result = build_matcher().match("帮我生成一份销售分析报告")

    assert result.matched is True
    assert result.confidence == 0.85


def test_priority_resolves_multiple_rule_conflicts() -> None:
    result = build_matcher().match("帮我生成报告")

    assert result.matched is True
    assert result.function_code == "REPORT_CREATE"
    assert result.intent_category == "报告生成型"
    assert result.target_engine == "report_engine"


def test_invalid_regex_is_ignored() -> None:
    matcher = build_matcher(
        rules=[
            make_rule("不会命中关键词", "REPORT_CREATE", pattern="[", priority=1),
        ],
    )

    result = matcher.match("这句话不会命中")

    assert result.matched is False


def test_inactive_rule_is_not_used() -> None:
    matcher = build_matcher(
        rules=[
            make_rule("生成报告", "REPORT_CREATE", priority=1, status="disabled"),
        ],
    )

    result = matcher.match("生成报告")

    assert result.matched is False


def test_inactive_function_is_not_returned() -> None:
    matcher = build_matcher(
        functions={
            "REPORT_CREATE": make_function("REPORT_CREATE", "报告生成型", "report_engine", status="disabled"),
        },
    )

    result = matcher.match("生成报告")

    assert result.matched is False


def test_matcher_skips_missing_function_and_uses_next_candidate() -> None:
    rules = [
        make_rule("生成报告", "MISSING_FUNCTION", pattern=r"生成.*报告", priority=1),
        make_rule("报告", "REPORT_GENERIC", pattern=r"报告", priority=50),
    ]
    matcher = build_matcher(
        rules=rules,
        functions={
            "REPORT_GENERIC": make_function("REPORT_GENERIC", "报告生成型", "report_engine"),
        },
    )

    result = matcher.match("生成报告")

    assert result.matched is True
    assert result.function_code == "REPORT_GENERIC"


def test_unmatched_result_schema_can_omit_none_fields() -> None:
    result = build_matcher().match("今天天气怎么样")

    assert result.model_dump(exclude_none=True) == {
        "level": 1,
        "matched": False,
    }


def test_matched_result_schema_matches_expected_output_shape() -> None:
    result = build_matcher().match("生成报告")

    assert result.model_dump(exclude_none=True) == {
        "level": 1,
        "matched": True,
        "function_code": "REPORT_CREATE",
        "intent_category": "报告生成型",
        "target_engine": "report_engine",
        "confidence": 1.0,
    }


def test_rule_engine_repository_queries_active_rules() -> None:
    session = MagicMock()
    scalar_result = MagicMock()
    scalar_result.all.return_value = []
    session.scalars.return_value = scalar_result
    repository = RuleEngineRepository(session)

    result = repository.list_active_rules()

    assert result == []
    session.scalars.assert_called_once()
