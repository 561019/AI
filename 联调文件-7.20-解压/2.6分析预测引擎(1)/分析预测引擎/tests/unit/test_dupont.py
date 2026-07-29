from decimal import Decimal

import pytest

from analysis_prediction_engine.calculators.core import ZeroDenominatorError
from analysis_prediction_engine.calculators.dupont import dupont_components


def test_dupont_roe_uses_unrounded_intermediates() -> None:
    result = dupont_components(
        net_income=Decimal("1"),
        revenue=Decimal("300"),
        total_assets=Decimal("300"),
        equity=Decimal("100"),
    )

    assert result == {
        "net_margin_percent": Decimal("0.33"),
        "asset_turnover": Decimal("1.0000"),
        "equity_multiplier": Decimal("3.0000"),
        "roe_percent": Decimal("1.00"),
    }


@pytest.mark.parametrize("field", ["revenue", "total_assets", "equity"])
def test_dupont_rejects_zero_denominators_with_domain_error(field: str) -> None:
    values = {
        "net_income": Decimal("1"),
        "revenue": Decimal("1"),
        "total_assets": Decimal("1"),
        "equity": Decimal("1"),
    }
    values[field] = Decimal("0")

    with pytest.raises(ZeroDenominatorError):
        dupont_components(**values)
