from decimal import Decimal

import pytest

from analysis_prediction_engine.calculators.trend import detect_z_score_anomalies, linear_slope, trend_label


def test_linear_slope_and_label_use_decimal_outputs() -> None:
    slope = linear_slope((Decimal("10"), Decimal("20"), Decimal("30")))

    assert slope == Decimal("10.0000")
    assert trend_label(slope) == "up"
    assert trend_label(Decimal("0")) == "stable"
    assert trend_label(Decimal("-0.1")) == "down"
    with pytest.raises(ValueError):
        trend_label(Decimal("0"), Decimal("-1"))


def test_z_score_detector_returns_traceable_indices() -> None:
    anomalies = detect_z_score_anomalies(
        (Decimal("10"), Decimal("10"), Decimal("10"), Decimal("100")),
        threshold=Decimal("1"),
    )

    assert anomalies == ({"index": 3, "value": Decimal("100"), "z_score": Decimal("1.73")},)
    with pytest.raises(ValueError):
        detect_z_score_anomalies((Decimal("1"), Decimal("2")), threshold=Decimal("-1"))
