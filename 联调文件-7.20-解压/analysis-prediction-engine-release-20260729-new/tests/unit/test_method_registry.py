"""Tests for method_registry — all methods registered and version constants consistent."""

from analysis_prediction_engine.method_registry import (
    REGISTERED_METHODS,
    MethodCategory,
    get_method,
    methods_by_category,
    method_versions_by_category,
    FINANCIAL_VERSION,
    BUSINESS_METRICS_VERSION,
    PRICE_FORECAST_VERSION,
    LLM_NARRATIVE_VERSION,
)


def test_all_categories_have_at_least_one_method():
    for category in MethodCategory:
        found = methods_by_category(category)
        assert len(found) >= 1, f"Category {category.value} has no registered methods"


def test_registered_methods_are_unique():
    ids = [m.method_id for m in REGISTERED_METHODS]
    assert len(ids) == len(set(ids)), f"Duplicate method_id found: {ids}"


def test_version_constants_match_registered_methods():
    """Each version constant should appear in at least one registered method."""
    versions_in_registry = {m.version for m in REGISTERED_METHODS}
    for v in (FINANCIAL_VERSION, BUSINESS_METRICS_VERSION, PRICE_FORECAST_VERSION, LLM_NARRATIVE_VERSION):
        assert v in versions_in_registry, f"Version {v} not found in any registered method"


def test_get_method_returns_correct_entry():
    m = get_method(FINANCIAL_VERSION)
    assert m is not None
    assert m.category == MethodCategory.COMPARISON


def test_get_method_returns_none_for_unknown_version():
    assert get_method("nonexistent-v99") is None


def test_method_versions_by_category_returns_frozenset():
    result = method_versions_by_category(MethodCategory.COMPARISON)
    assert isinstance(result, frozenset)
    assert FINANCIAL_VERSION in result
    assert BUSINESS_METRICS_VERSION in result


def test_all_methods_have_required_fields():
    for m in REGISTERED_METHODS:
        assert m.method_id.startswith("METH-"), f"{m.method_id}: bad id format"
        assert len(m.name) >= 2, f"{m.method_id}: name too short"
        assert isinstance(m.category, MethodCategory), f"{m.method_id}: bad category"
        assert len(m.version) >= 3, f"{m.method_id}: version too short"
        assert len(m.description) >= 10, f"{m.method_id}: description too short"
        assert "." in m.source_module, f"{m.method_id}: source_module should be dotted path"


def test_four_categories_match_design():
    """Design doc specifies exactly four: 对比、拆解、原因分析、预测."""
    categories = {c for c in MethodCategory}
    assert categories == {
        MethodCategory.COMPARISON,
        MethodCategory.DECOMPOSITION,
        MethodCategory.CAUSE_ANALYSIS,
        MethodCategory.PREDICTION,
    }
