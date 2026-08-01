from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence

from analysis_prediction_engine.calculators.core import to_decimal


SLOPE_QUANTUM = Decimal("0.0001")
ZSCORE_QUANTUM = Decimal("0.01")


def linear_slope(values: Sequence[Decimal]) -> Decimal:
    if len(values) < 2:
        raise ValueError("at least two values are required for a trend slope")
    decimal_values = tuple(to_decimal(value) for value in values)
    count = Decimal(len(decimal_values))
    mean_x = Decimal(len(decimal_values) - 1) / Decimal("2")
    mean_y = sum(decimal_values) / count
    numerator = sum(
        (Decimal(index) - mean_x) * (value - mean_y)
        for index, value in enumerate(decimal_values)
    )
    denominator = sum((Decimal(index) - mean_x) ** 2 for index in range(len(decimal_values)))
    return (numerator / denominator).quantize(SLOPE_QUANTUM, ROUND_HALF_UP)


def trend_label(slope: Decimal, deadband: Decimal = Decimal("0")) -> str:
    decimal_slope = to_decimal(slope)
    decimal_deadband = to_decimal(deadband)
    if decimal_deadband < 0:
        raise ValueError("trend deadband must not be negative")
    if decimal_slope > decimal_deadband:
        return "up"
    if decimal_slope < -decimal_deadband:
        return "down"
    return "stable"


def detect_z_score_anomalies(
    values: Sequence[Decimal], threshold: Decimal = Decimal("3")
) -> tuple[dict[str, Decimal | int], ...]:
    if len(values) < 2:
        return ()
    decimal_values = tuple(to_decimal(value) for value in values)
    mean = sum(decimal_values) / Decimal(len(decimal_values))
    variance = sum((value - mean) ** 2 for value in decimal_values) / Decimal(len(decimal_values))
    standard_deviation = variance.sqrt()
    if standard_deviation == 0:
        return ()
    minimum_score = to_decimal(threshold)
    if minimum_score < 0:
        raise ValueError("anomaly threshold must not be negative")
    anomalies: list[dict[str, Decimal | int]] = []
    for index, value in enumerate(decimal_values):
        raw_score = (value - mean) / standard_deviation
        score = raw_score.quantize(ZSCORE_QUANTUM, ROUND_HALF_UP)
        if abs(raw_score) >= minimum_score:
            anomalies.append({"index": index, "value": value, "z_score": score})
    return tuple(anomalies)
