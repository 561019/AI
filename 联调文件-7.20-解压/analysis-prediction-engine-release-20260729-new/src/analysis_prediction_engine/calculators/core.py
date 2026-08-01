from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


PERCENT_QUANTUM = Decimal("0.01")


class MissingValueError(ValueError):
    """Raised when a deterministic calculation lacks a required value."""


class ZeroDenominatorError(ZeroDivisionError):
    """Raised when a ratio or rate has a zero denominator."""


def to_decimal(value: Any) -> Decimal:
    if value is None:
        raise MissingValueError("calculation value is required")
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("calculation values must be Decimal-compatible strings or integers")
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise TypeError("calculation value is not Decimal-compatible") from exc
    if not decimal_value.is_finite():
        raise ValueError("calculation value must be finite")
    return decimal_value


def _percentage(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        raise ZeroDenominatorError("percentage denominator must not be zero")
    return (numerator / denominator * Decimal("100")).quantize(PERCENT_QUANTUM, ROUND_HALF_UP)


def year_over_year_percent(current: Any, prior_year: Any) -> Decimal:
    current_value = to_decimal(current)
    prior_value = to_decimal(prior_year)
    return _percentage(current_value - prior_value, abs(prior_value))


def period_over_period_percent(current: Any, prior_period: Any) -> Decimal:
    return year_over_year_percent(current, prior_period)


def ratio_percent(part: Any, whole: Any) -> Decimal:
    return _percentage(to_decimal(part), to_decimal(whole))


def difference(actual: Any, target: Any) -> Decimal:
    return (to_decimal(actual) - to_decimal(target)).quantize(PERCENT_QUANTUM, ROUND_HALF_UP)


def threshold_comparison(actual: Any, target: Any) -> dict[str, Decimal | bool]:
    actual_raw = to_decimal(actual)
    target_raw = to_decimal(target)
    return {
        "actual": actual_raw.quantize(PERCENT_QUANTUM, ROUND_HALF_UP),
        "target": target_raw.quantize(PERCENT_QUANTUM, ROUND_HALF_UP),
        "difference": difference(actual_raw, target_raw),
        "is_exceeded": actual_raw > target_raw,
    }
