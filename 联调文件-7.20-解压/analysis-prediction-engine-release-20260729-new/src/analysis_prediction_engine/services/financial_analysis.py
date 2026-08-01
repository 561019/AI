from collections import defaultdict
from decimal import Decimal

from analysis_prediction_engine.calculators.core import (
    ZeroDenominatorError,
    period_over_period_percent,
    year_over_year_percent,
)
from analysis_prediction_engine.calculators.dupont import dupont_components
from analysis_prediction_engine.calculators.trend import detect_z_score_anomalies, linear_slope, trend_label
from analysis_prediction_engine.traceability.provenance import build_provenance_reference

from analysis_prediction_engine.method_registry import FINANCIAL_VERSION as FORMULA_VERSION


def _year_ago_period(period: str) -> str:
    year, month = period.split("-", maxsplit=1)
    return f"{int(year) - 1:04d}-{month}"


def _previous_month_period(period: str) -> str:
    year, month = (int(value) for value in period.split("-", maxsplit=1))
    if month == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"


def _append_metric_provenance(
    references: list[object],
    *,
    output_field: str,
    source_record: object,
    metric: str,
) -> None:
    references.append(
        build_provenance_reference(
            output_field=output_field,
            source_record_id=source_record.source_record_id,
            source_field=f"metrics.{metric}",
            period=source_record.period,
            formula_version=FORMULA_VERSION,
        )
    )


def analyze_financial_statement(request) -> dict[str, object]:
    records = tuple(sorted(request.records, key=lambda record: record.period))
    by_period = {record.period: record for record in records}
    metric_records: dict[str, list[tuple[object, Decimal]]] = defaultdict(list)
    for record in records:
        for metric, value in record.metrics.items():
            metric_records[metric].append((record, value))

    output_metrics: dict[str, dict[str, object]] = {}
    provenance: list[object] = []

    for metric, entries in metric_records.items():
        values = tuple(value for _, value in entries)

        # --- Per-period computations (NEW: every period gets MoM + YoY) ---
        period_rows: list[dict[str, object]] = []
        for record, value in entries:
            row: dict[str, object] = {"period": record.period, "value": value}

            # MoM
            prev_period = _previous_month_period(record.period)
            prev_record = by_period.get(prev_period)
            if prev_record is not None and metric in prev_record.metrics:
                try:
                    row["period_over_period_percent"] = period_over_period_percent(
                        value, prev_record.metrics[metric]
                    )
                except ZeroDenominatorError:
                    row["period_over_period_percent"] = None
            else:
                row["period_over_period_percent"] = None

            # YoY
            yoy_period = _year_ago_period(record.period)
            yoy_record = by_period.get(yoy_period)
            if yoy_record is not None and metric in yoy_record.metrics:
                try:
                    row["year_over_year_percent"] = year_over_year_percent(
                        value, yoy_record.metrics[metric]
                    )
                except ZeroDenominatorError:
                    row["year_over_year_percent"] = None
            else:
                row["year_over_year_percent"] = None

            period_rows.append(row)

        # --- Summary (last period, backward compatible) ---
        current_record, current_value = entries[-1]
        summary: dict[str, object] = {
            "current": current_value,
            "by_period": tuple(period_rows),
        }

        _append_metric_provenance(provenance, output_field=f"financial.{metric}.current",
                                  source_record=current_record, metric=metric)

        # Trend (over all periods)
        try:
            slope = linear_slope(values)
            summary["trend_slope"] = slope
            summary["trend"] = trend_label(slope)
        except ValueError:
            summary["trend_status"] = "not_computable"
            summary["trend_reason"] = "at least two periods are required"

        # Anomalies
        summary["anomalies"] = detect_z_score_anomalies(values, threshold=Decimal("1.5"))

        # Provenance for per-period computations
        for row in period_rows:
            src_record = by_period.get(row["period"])
            if src_record is None:
                continue
            if row.get("period_over_period_percent") is not None:
                pop_period = _previous_month_period(row["period"])
                pop_record = by_period.get(pop_period)
                if pop_record:
                    for sr in (src_record, pop_record):
                        _append_metric_provenance(provenance,
                            output_field=f"financial.{metric}.period_over_period_percent",
                            source_record=sr, metric=metric)
            if row.get("year_over_year_percent") is not None:
                yoy_period = _year_ago_period(row["period"])
                yoy_record = by_period.get(yoy_period)
                if yoy_record:
                    for sr in (src_record, yoy_record):
                        _append_metric_provenance(provenance,
                            output_field=f"financial.{metric}.year_over_year_percent",
                            source_record=sr, metric=metric)

        # YoY / MoM for last period (backward compat)
        last = period_rows[-1]
        if last["year_over_year_percent"] is not None:
            summary["year_over_year_percent"] = last["year_over_year_percent"]
        else:
            summary["year_over_year_percent"] = None
            summary["year_over_year_status"] = "not_computable"
        if last["period_over_period_percent"] is not None:
            summary["period_over_period_percent"] = last["period_over_period_percent"]
        else:
            summary["period_over_period_percent"] = None
            summary["period_over_period_status"] = "not_computable"

        output_metrics[metric] = summary

    # ---- DuPont: compute for EVERY period that has required metrics ----
    required = {"net_income", "revenue", "total_assets", "equity"}
    dupont_rows: list[dict[str, object]] = []

    for record in records:
        if required.issubset(record.metrics):
            try:
                components = dupont_components(**{name: record.metrics[name] for name in required})
                components["period"] = record.period
                dupont_rows.append(components)
            except ZeroDivisionError:
                dupont_rows.append({"period": record.period, "status": "not_computable", "reason": "denominator is zero"})
        else:
            dupont_rows.append({"period": record.period, "status": "not_computable", "reason": "missing required metrics"})

    # Backward compat: last period DuPont summary
    dupont_summary: dict[str, object]
    if dupont_rows and dupont_rows[-1].get("roe_percent") is not None:
        dupont_summary = dict(dupont_rows[-1])
    else:
        dupont_summary = {"status": "not_computable", "reason": "last period cannot compute DuPont"}
    dupont_summary["by_period"] = tuple(dupont_rows)

    conclusions = (
        {
            "kind": "financial_metric",
            "status": "complete",
            "details": {
                "metric_count": len(output_metrics),
                "period": records[-1].period,
                "period_count": len(records),
            },
        },
    )

    return {
        "schema_version": "v1",
        "trace_id": request.trace_id,
        "analysis_type": "financial_statement",
        "status": "complete",
        "decision_reference_only": True,
        "human_confirmation_required": True,
        "effective": False,
        "metrics": output_metrics,
        "dupont": dupont_summary,
        "conclusions": conclusions,
        "provenance": tuple(provenance),
        "calculation_metadata": ({"algorithm_version": "financial-v1", "formula_version": FORMULA_VERSION},),
    }
