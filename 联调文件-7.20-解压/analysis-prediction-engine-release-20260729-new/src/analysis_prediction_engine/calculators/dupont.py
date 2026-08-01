from decimal import Decimal, ROUND_HALF_UP

from analysis_prediction_engine.calculators.core import (
    ZeroDenominatorError,
    ratio_percent,
    to_decimal,
)


RATIO_QUANTUM = Decimal("0.0001")
PERCENT_QUANTUM = Decimal("0.01")


def _divide(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        raise ZeroDenominatorError("DuPont denominator must not be zero")
    return numerator / denominator


def dupont_components(
    *, net_income: Decimal, revenue: Decimal, total_assets: Decimal, equity: Decimal
) -> dict[str, Decimal]:
    net_income_value = to_decimal(net_income)
    revenue_value = to_decimal(revenue)
    assets_value = to_decimal(total_assets)
    equity_value = to_decimal(equity)
    net_margin_raw = _divide(net_income_value, revenue_value)
    asset_turnover_raw = _divide(revenue_value, assets_value)
    equity_multiplier_raw = _divide(assets_value, equity_value)
    roe_percent = (net_margin_raw * asset_turnover_raw * equity_multiplier_raw * Decimal("100")).quantize(
        PERCENT_QUANTUM, ROUND_HALF_UP
    )
    return {
        "net_margin_percent": (net_margin_raw * Decimal("100")).quantize(
            PERCENT_QUANTUM, ROUND_HALF_UP
        ),
        "asset_turnover": asset_turnover_raw.quantize(RATIO_QUANTUM, ROUND_HALF_UP),
        "equity_multiplier": equity_multiplier_raw.quantize(RATIO_QUANTUM, ROUND_HALF_UP),
        "roe_percent": roe_percent,
    }
