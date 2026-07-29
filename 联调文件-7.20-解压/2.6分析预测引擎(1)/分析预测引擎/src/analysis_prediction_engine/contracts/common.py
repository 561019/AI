from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AnalysisType(str, Enum):
    FINANCIAL_STATEMENT = "financial_statement"
    PRICE_FORECAST = "price_forecast"
    BUSINESS_METRIC = "business_metric"


class TraceableModel(FrozenModel):
    schema_version: str = Field(pattern=r"^v1$")
    trace_id: str = Field(min_length=1)

    @field_validator("trace_id")
    @classmethod
    def trace_id_must_not_be_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("trace_id must not be blank")
        return value


class ProvenanceReference(FrozenModel):
    output_field: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    source_field: str = Field(min_length=1)
    period: str = Field(min_length=1)
    formula_version: str = Field(min_length=1)


class CalculationMetadata(FrozenModel):
    algorithm_version: str = Field(min_length=1)
    formula_version: str = Field(min_length=1)
