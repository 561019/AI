from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Annotated, Literal, Mapping

from pydantic import Field, TypeAdapter, field_validator, model_validator

from analysis_prediction_engine.contracts.common import AnalysisType, FrozenModel, TraceableModel


_PERIOD_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
_COST_RATIO_LIMITS = {
    "sales_cost_ratio",
    "delivery_cost_ratio",
    "operating_cost_ratio",
}


def _require_year_month(value: str) -> str:
    import re

    if not re.fullmatch(_PERIOD_PATTERN, value):
        raise ValueError("period must use YYYY-MM format with a valid month")
    return value


MAX_DECIMAL_DIGITS = 24
MAX_DECIMAL_ABS_EXPONENT = 18


def _require_decimal_wire_value(value: object) -> object:
    if not isinstance(value, str):
        raise ValueError("decimal inputs must be JSON strings")
    try:
        decimal_value = Decimal(value)
    except Exception as exc:
        raise ValueError("decimal input must be valid") from exc
    if not decimal_value.is_finite():
        raise ValueError("decimal input must be finite")
    digit_count = len(decimal_value.as_tuple().digits)
    if digit_count > MAX_DECIMAL_DIGITS or abs(decimal_value.adjusted()) > MAX_DECIMAL_ABS_EXPONENT:
        raise ValueError("decimal input exceeds the supported precision or magnitude")
    return value


class FinancialPeriodRecord(FrozenModel):
    period: str = Field(min_length=7, max_length=7)
    source_record_id: str = Field(min_length=1)
    metrics: Mapping[str, Decimal] = Field(min_length=1)

    @field_validator("metrics", mode="before")
    @classmethod
    def metrics_must_not_contain_floats(cls, value: object) -> object:
        if isinstance(value, dict):
            for numeric_value in value.values():
                _require_decimal_wire_value(numeric_value)
        return value

    @field_validator("period")
    @classmethod
    def period_must_be_year_month(cls, value: str) -> str:
        return _require_year_month(value)

    @model_validator(mode="after")
    def freeze_metrics(self) -> "FinancialPeriodRecord":
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))
        return self


class PriceRecord(FrozenModel):
    date: date
    source_record_id: str = Field(min_length=1)
    price: Decimal = Field(gt=0)

    @field_validator("price", mode="before")
    @classmethod
    def price_must_not_be_float(cls, value: object) -> object:
        return _require_decimal_wire_value(value)


class BusinessMetricRecord(FrozenModel):
    period: str = Field(min_length=7, max_length=7)
    source_record_id: str = Field(min_length=1)
    revenue: Decimal = Field(ge=0)
    sales_cost: Decimal = Field(ge=0)
    delivery_cost: Decimal = Field(ge=0)
    operating_cost: Decimal = Field(ge=0)

    @field_validator("revenue", "sales_cost", "delivery_cost", "operating_cost", mode="before")
    @classmethod
    def business_values_must_not_be_floats(cls, value: object) -> object:
        return _require_decimal_wire_value(value)

    @field_validator("period")
    @classmethod
    def period_must_be_year_month(cls, value: str) -> str:
        return _require_year_month(value)


class TargetLimits(FrozenModel):
    sales_cost_ratio: Decimal = Field(ge=0, le=100)
    delivery_cost_ratio: Decimal = Field(ge=0, le=100)
    operating_cost_ratio: Decimal = Field(ge=0, le=100)

    @field_validator("sales_cost_ratio", "delivery_cost_ratio", "operating_cost_ratio", mode="before")
    @classmethod
    def target_limits_must_not_be_floats(cls, value: object) -> object:
        return _require_decimal_wire_value(value)


class FinancialStatementRequest(TraceableModel):
    analysis_type: Literal[AnalysisType.FINANCIAL_STATEMENT]
    records: tuple[FinancialPeriodRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def periods_must_be_unique(self) -> "FinancialStatementRequest":
        if len({record.period for record in self.records}) != len(self.records):
            raise ValueError("financial records must have unique periods")
        return self


class PriceForecastRequest(TraceableModel):
    analysis_type: Literal[AnalysisType.PRICE_FORECAST]
    records: tuple[PriceRecord, ...] = Field(min_length=3)
    forecast_horizon: int = Field(ge=1, le=24)

    @model_validator(mode="after")
    def dates_must_form_a_contiguous_monthly_series(self) -> "PriceForecastRequest":
        dates = tuple(sorted(record.date for record in self.records))
        if len(set(dates)) != len(dates):
            raise ValueError("price records must have unique dates")
        if len({record.source_record_id for record in self.records}) != len(self.records):
            raise ValueError("price records must have unique source_record_id values")
        if any(value.day != 1 for value in dates):
            raise ValueError("price records must use the first day of each month")
        for previous, current in zip(dates, dates[1:]):
            expected_year = previous.year + (previous.month // 12)
            expected_month = previous.month % 12 + 1
            if (current.year, current.month) != (expected_year, expected_month):
                raise ValueError("price records must be contiguous monthly observations")
        latest_month_index = dates[-1].year * 12 + dates[-1].month - 1
        maximum_month_index = date.max.year * 12 + date.max.month - 1
        if latest_month_index + self.forecast_horizon > maximum_month_index:
            raise ValueError("forecast horizon exceeds the supported calendar range")
        return self


class BusinessMetricRequest(TraceableModel):
    analysis_type: Literal[AnalysisType.BUSINESS_METRIC]
    record: BusinessMetricRecord
    target_limits: TargetLimits


AnalysisRequest = Annotated[
    FinancialStatementRequest | PriceForecastRequest | BusinessMetricRequest,
    Field(discriminator="analysis_type"),
]

_analysis_request_adapter = TypeAdapter(AnalysisRequest)


def parse_analysis_request(payload: object) -> AnalysisRequest:
    return _analysis_request_adapter.validate_python(payload)
