from datetime import date

from analysis_prediction_engine.contracts.requests import PriceForecastRequest
from analysis_prediction_engine.forecasting.price_trend import forecast_series
from analysis_prediction_engine.method_registry import PRICE_FORECAST_VERSION
from analysis_prediction_engine.traceability.provenance import build_provenance_reference


def _monthly_date_after(start: date, months: int) -> date:
    index = start.year * 12 + start.month - 1 + months
    year, month_index = divmod(index, 12)
    return date(year, month_index + 1, 1)


def _not_computable_result(request: PriceForecastRequest, reason: str) -> dict[str, object]:
    records = tuple(sorted(request.records, key=lambda record: record.date))
    source_ids = tuple(record.source_record_id for record in records)
    return {
        "schema_version": "v1",
        "trace_id": request.trace_id,
        "analysis_type": "price_forecast",
        "status": "not_computable",
        "decision_reference_only": True,
        "human_confirmation_required": True,
        "effective": False,
        "uncertainty": {"status": "not_computable", "band_type": "deterministic_residual_band", "message": reason},
        "volatility": {"status": "not_computable"},
        "forecasts": (),
        "history_window": {"start": records[0].date, "end": records[-1].date, "source_record_ids": source_ids},
        "conclusions": ({"kind": "price_trend_forecast", "status": "not_computable", "details": {"reason": reason}},),
        "provenance": (),
        "calculation_metadata": ({"algorithm_version": PRICE_FORECAST_VERSION, "formula_version": PRICE_FORECAST_VERSION},),
    }


def forecast_prices(request: PriceForecastRequest) -> dict[str, object]:
    records = tuple(sorted(request.records, key=lambda record: record.date))
    try:
        series = forecast_series(tuple(record.price for record in records), request.forecast_horizon)
    except ValueError as error:
        return _not_computable_result(request, str(error))
    last_date = records[-1].date
    source_ids = tuple(record.source_record_id for record in records)
    forecasts = tuple(
        {
            **forecast,
            "date": _monthly_date_after(last_date, forecast["step"]),
            "source_record_ids": source_ids,
        }
        for forecast in series["forecasts"]
    )
    provenance = tuple(
        reference
        for forecast in forecasts
        for record in records
        for reference in (
            build_provenance_reference(
                output_field=f"price.forecast.step_{forecast['step']}",
                source_record_id=record.source_record_id,
                source_field="price",
                period=f"{records[0].date}/{records[-1].date}",
                formula_version=series["model_version"],
            ),
            build_provenance_reference(
                output_field="price.volatility",
                source_record_id=record.source_record_id,
                source_field="price",
                period=f"{records[0].date}/{records[-1].date}",
                formula_version=series["model_version"],
            ),
        )
    )
    return {
        "schema_version": "v1",
        "trace_id": request.trace_id,
        "analysis_type": "price_forecast",
        "status": "complete",
        "decision_reference_only": True,
        "human_confirmation_required": True,
        "effective": False,
        "uncertainty": {
            "status": "available",
            "band_type": "deterministic_residual_band",
            "message": "Forecast intervals are uncalibrated deterministic residual bands for decision reference only.",
        },
        "volatility": {
            "slope": series["slope"],
            "trend": series["trend"],
            "price_range": series["price_range"],
            "relative_range_percent": series["relative_range_percent"],
            "model_version": series["model_version"],
        },
        "forecasts": forecasts,
        "history_window": {
            "start": records[0].date,
            "end": records[-1].date,
            "source_record_ids": source_ids,
        },
        "conclusions": (
            {
                "kind": "price_trend_forecast",
                "status": "complete",
                "details": {
                    "trend": series["trend"],
                    "forecast_horizon_months": request.forecast_horizon,
                    "history_start": records[0].date,
                    "history_end": records[-1].date,
                },
            },
        ),
        "provenance": provenance,
        "calculation_metadata": (
            {"algorithm_version": series["model_version"], "formula_version": series["model_version"]},
        ),
    }
