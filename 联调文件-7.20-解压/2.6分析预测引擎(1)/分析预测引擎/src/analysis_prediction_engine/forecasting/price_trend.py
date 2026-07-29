from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence

from analysis_prediction_engine.calculators.core import to_decimal
from analysis_prediction_engine.calculators.trend import linear_slope, trend_label

VALUE_QUANTUM = Decimal("0.01")


def forecast_series(values: Sequence[Decimal], horizon: int) -> dict[str, object]:
    if len(values) < 3:
        raise ValueError("at least three historical prices are required")
    if horizon < 1 or horizon > 24:
        raise ValueError("forecast horizon must be between 1 and 24")
    prices = tuple(to_decimal(value) for value in values)
    if any(price <= 0 for price in prices):
        raise ValueError("historical prices must be positive")
    slope = linear_slope(prices)
    intercept = sum(prices) / Decimal(len(prices)) - slope * Decimal(len(prices) - 1) / Decimal("2")
    residuals = tuple(
        price - (intercept + slope * Decimal(index)) for index, price in enumerate(prices)
    )
    residual_variance = sum(residual * residual for residual in residuals) / Decimal(len(residuals))
    residual_scale = residual_variance.sqrt()
    uncertainty = (residual_scale * Decimal("1.96")).quantize(VALUE_QUANTUM, ROUND_HALF_UP)
    forecasts = tuple(
        {
            "step": step,
            "value": (intercept + slope * Decimal(len(prices) - 1 + step)).quantize(
                VALUE_QUANTUM, ROUND_HALF_UP
            ),
            "lower": (intercept + slope * Decimal(len(prices) - 1 + step) - uncertainty).quantize(
                VALUE_QUANTUM, ROUND_HALF_UP
            ),
            "upper": (intercept + slope * Decimal(len(prices) - 1 + step) + uncertainty).quantize(
                VALUE_QUANTUM, ROUND_HALF_UP
            ),
        }
        for step in range(1, horizon + 1)
    )
    if any(forecast["value"] <= 0 or forecast["lower"] <= 0 for forecast in forecasts):
        raise ValueError("forecast leaves the supported positive-price domain")
    minimum_price = min(prices)
    maximum_price = max(prices)
    price_range = (maximum_price - minimum_price).quantize(VALUE_QUANTUM, ROUND_HALF_UP)
    relative_range_percent = (
        price_range / minimum_price * Decimal("100")
    ).quantize(VALUE_QUANTUM, ROUND_HALF_UP)
    return {
        "model_version": "linear-trend-v1",
        "slope": slope,
        "trend": trend_label(slope),
        "uncertainty": uncertainty,
        "price_range": price_range,
        "relative_range_percent": relative_range_percent,
        "forecasts": forecasts,
    }
