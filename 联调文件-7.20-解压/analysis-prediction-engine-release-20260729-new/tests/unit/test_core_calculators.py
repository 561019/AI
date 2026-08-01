from decimal import Decimal

import pytest

from analysis_prediction_engine.calculators.core import (
    MissingValueError,
    ZeroDenominatorError,
    difference,
    period_over_period_percent,
    ratio_percent,
    threshold_comparison,
    year_over_year_percent,
)


def test_year_over_year_uses_absolute_prior_value() -> None:
    assert year_over_year_percent(Decimal("120"), Decimal("100")) == Decimal("20.00")
    assert year_over_year_percent(Decimal("80"), Decimal("-100")) == Decimal("180.00")


def test_percentage_calculations_reject_zero_or_missing_denominators() -> None:
    with pytest.raises(ZeroDenominatorError):
        period_over_period_percent(Decimal("1"), Decimal("0"))
    with pytest.raises(MissingValueError):
        ratio_percent(None, Decimal("10"))


def test_threshold_comparison_has_explicit_exceeded_flag() -> None:
    comparison = threshold_comparison(Decimal("36"), Decimal("35"))

    assert comparison == {
        "actual": Decimal("36.00"),
        "target": Decimal("35.00"),
        "difference": Decimal("1.00"),
        "is_exceeded": True,
    }
    assert difference(Decimal("30"), Decimal("35")) == Decimal("-5.00")


def test_threshold_comparison_decides_from_unrounded_values() -> None:
    comparison = threshold_comparison(Decimal("1.004"), Decimal("1.003"))

    assert comparison["is_exceeded"] is True
    assert comparison["difference"] == Decimal("0.00")
