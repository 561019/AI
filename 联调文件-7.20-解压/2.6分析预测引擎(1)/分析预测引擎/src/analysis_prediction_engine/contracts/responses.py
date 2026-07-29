from typing import Annotated, Any, Literal

from pydantic import Field, TypeAdapter

from analysis_prediction_engine.contracts.common import (
    AnalysisType,
    CalculationMetadata,
    FrozenModel,
    ProvenanceReference,
    TraceableModel,
)


class StructuredConclusion(FrozenModel):
    kind: str = Field(min_length=1)
    status: Literal["complete", "partial", "not_computable"]
    details: dict[str, Any]


class AnalysisResult(TraceableModel):
    analysis_type: AnalysisType
    status: Literal["complete", "partial", "not_computable"] = "complete"
    conclusions: tuple[StructuredConclusion, ...] = Field(min_length=1)
    provenance: tuple[ProvenanceReference, ...] = ()
    calculation_metadata: tuple[CalculationMetadata, ...] = ()
    decision_reference_only: Literal[True] = True
    human_confirmation_required: Literal[True] = True
    effective: Literal[False] = False


class FinancialAnalysisResult(AnalysisResult):
    analysis_type: Literal[AnalysisType.FINANCIAL_STATEMENT]
    metrics: dict[str, dict[str, Any]]
    dupont: dict[str, Any]


class PriceForecastResult(AnalysisResult):
    analysis_type: Literal[AnalysisType.PRICE_FORECAST]
    uncertainty: dict[str, Any]
    volatility: dict[str, Any]
    forecasts: tuple[dict[str, Any], ...]
    history_window: dict[str, Any]


class BusinessMetricResult(AnalysisResult):
    analysis_type: Literal[AnalysisType.BUSINESS_METRIC]
    net_profit: Any
    cost_ratios: dict[str, Any] | None
    target_comparisons: dict[str, Any] | None
    alert_candidates: tuple[dict[str, Any], ...]
    metric_status: Literal["not_computable"] | None = None
    metric_reason: str | None = None


AnalysisResponse = Annotated[
    FinancialAnalysisResult | PriceForecastResult | BusinessMetricResult,
    Field(discriminator="analysis_type"),
]

_analysis_response_adapter = TypeAdapter(AnalysisResponse)


def validate_analysis_response(payload: object) -> AnalysisResponse:
    return _analysis_response_adapter.validate_python(payload)


class AnalysisError(TraceableModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
