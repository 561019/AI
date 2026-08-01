from decimal import Decimal

from analysis_prediction_engine.calculators.core import (
    ZeroDenominatorError,
    ratio_percent,
    threshold_comparison,
)
from analysis_prediction_engine.contracts.requests import BusinessMetricRequest
from analysis_prediction_engine.method_registry import BUSINESS_METRICS_VERSION as FORMULA_VERSION
from analysis_prediction_engine.traceability.provenance import build_provenance_reference


def _record_provenance(
    *, output_field: str, request: BusinessMetricRequest, source_fields: tuple[str, ...]
) -> tuple[object, ...]:
    return tuple(
        build_provenance_reference(
            output_field=output_field,
            source_record_id=request.record.source_record_id,
            source_field=field,
            period=request.record.period,
            formula_version=FORMULA_VERSION,
        )
        for field in source_fields
    )


def analyze_business_metrics(request: BusinessMetricRequest) -> dict[str, object]:
    record = request.record
    net_profit = (
        record.revenue - record.sales_cost - record.delivery_cost - record.operating_cost
    ).quantize(Decimal("0.01"))
    net_profit_provenance = _record_provenance(
        output_field="business.net_profit",
        request=request,
        source_fields=(
            "record.revenue",
            "record.sales_cost",
            "record.delivery_cost",
            "record.operating_cost",
        ),
    )
    costs = {
        "sales_cost_ratio": record.sales_cost,
        "delivery_cost_ratio": record.delivery_cost,
        "operating_cost_ratio": record.operating_cost,
    }
    try:
        ratios = {name: ratio_percent(value, record.revenue) for name, value in costs.items()}
    except ZeroDenominatorError:
        return {
            "schema_version": "v1",
            "trace_id": request.trace_id,
            "analysis_type": "business_metric",
            "status": "not_computable",
            "decision_reference_only": True,
            "human_confirmation_required": True,
            "effective": False,
            "net_profit": net_profit,
            "cost_ratios": None,
            "metric_status": "not_computable",
            "metric_reason": "revenue must not be zero when calculating cost ratios",
            "target_comparisons": None,
            "alert_candidates": (),
            "conclusions": (
                {
                    "kind": "business_target_comparison",
                    "status": "not_computable",
                    "details": {"reason": "revenue must not be zero when calculating cost ratios"},
                },
            ),
            "provenance": net_profit_provenance,
            "calculation_metadata": ({"algorithm_version": FORMULA_VERSION, "formula_version": FORMULA_VERSION},),
        }
    comparisons = {
        name: threshold_comparison(ratio, getattr(request.target_limits, name))
        for name, ratio in ratios.items()
    }
    alerts = tuple(
        {
            "metric": name,
            "actual": comparison["actual"],
            "target": comparison["target"],
            "excess": comparison["difference"],
            "severity": "warning",
            "source_record_id": record.source_record_id,
        }
        for name, comparison in comparisons.items()
        if comparison["is_exceeded"]
    )
    provenance: list[object] = list(net_profit_provenance)
    for name in ratios:
        source_field = f"record.{name.removesuffix('_ratio')}"
        provenance.extend(
            _record_provenance(
                output_field=f"business.{name}",
                request=request,
                source_fields=("record.revenue", source_field),
            )
        )
        provenance.extend(
            _record_provenance(
                output_field=f"business.{name}.comparison",
                request=request,
                source_fields=(source_field, "record.revenue", f"target_limits.{name}"),
            )
        )
    return {
        "schema_version": "v1",
        "trace_id": request.trace_id,
        "analysis_type": "business_metric",
        "status": "complete",
        "decision_reference_only": True,
        "human_confirmation_required": True,
        "effective": False,
        "net_profit": net_profit,
        "cost_ratios": ratios,
        "target_comparisons": comparisons,
        "alert_candidates": alerts,
        "conclusions": (
            {
                "kind": "business_target_comparison",
                "status": "complete",
                "details": {"exceeded_metrics": tuple(alert["metric"] for alert in alerts)},
            },
        ),
        "provenance": tuple(provenance),
        "calculation_metadata": ({"algorithm_version": FORMULA_VERSION, "formula_version": FORMULA_VERSION},),
    }
