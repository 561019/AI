from datetime import date
from decimal import Decimal
from pathlib import Path

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from analysis_prediction_engine.contracts.common import AnalysisType
from analysis_prediction_engine.contracts.requests import AnalysisRequest
from analysis_prediction_engine.contracts.responses import validate_analysis_response
from analysis_prediction_engine.services.business_metrics import analyze_business_metrics
from analysis_prediction_engine.services.chat_service import chat as chat_service
from analysis_prediction_engine.services.financial_analysis import analyze_financial_statement
from analysis_prediction_engine.services.llm_narrative import narrate
from analysis_prediction_engine.services.price_forecast import forecast_prices

router = APIRouter()

_DASHBOARD_PATH = Path(__file__).resolve().parent.parent.parent.parent / "dashboard.html"
_CHAT_PATH = Path(__file__).resolve().parent.parent.parent.parent / "chat.html"


@router.get("/", response_class=HTMLResponse)
def serve_dashboard() -> str:
    if _DASHBOARD_PATH.exists():
        return _DASHBOARD_PATH.read_text(encoding="utf-8")
    return "<html><body><h1>Dashboard not found</h1></body></html>"


@router.get("/chat", response_class=HTMLResponse)
def serve_chat() -> str:
    if _CHAT_PATH.exists():
        return _CHAT_PATH.read_text(encoding="utf-8")
    return "<html><body><h1>Chat not found</h1></body></html>"


@router.post("/v1/analysis-jobs/evaluate", response_model=None)
def evaluate_analysis_job(request: AnalysisRequest) -> JSONResponse:
    if request.analysis_type is AnalysisType.FINANCIAL_STATEMENT:
        payload = analyze_financial_statement(request)
    elif request.analysis_type is AnalysisType.PRICE_FORECAST:
        payload = forecast_prices(request)
    else:
        payload = analyze_business_metrics(request)
    response = validate_analysis_response(payload)
    return JSONResponse(status_code=200, content=_to_json_value(response.model_dump()))


@router.get("/v1/monitor/latest")
def monitor_latest() -> JSONResponse:
    """Return latest business_metric analysis without LLM."""
    import json
    from pathlib import Path
    from analysis_prediction_engine.contracts.requests import BusinessMetricRequest
    from analysis_prediction_engine.services.business_metrics import analyze_business_metrics

    data_dir = Path(__file__).resolve().parent.parent.parent.parent
    files = sorted(data_dir.glob("*律所经营指标_请求体.json"), reverse=True)
    if not files:
        return JSONResponse(status_code=404, content={"error": "no business metric files"})
    raw = json.loads(files[0].read_text(encoding="utf-8"))
    request = BusinessMetricRequest.model_validate(raw)
    result = analyze_business_metrics(request)
    out = _to_json_value(result)
    out["period"] = raw["record"]["period"]
    return JSONResponse(status_code=200, content=out)


@router.post("/v1/analysis-jobs/narrate")
async def narrate_analysis_job(request: Request) -> JSONResponse:
    """Generate LLM narrative for an already-computed analysis result."""
    payload = await request.json()
    result = narrate(payload)
    return JSONResponse(status_code=200, content=result)


@router.post("/v1/analysis-jobs/analyze")
def analyze_and_narrate(request: AnalysisRequest) -> JSONResponse:
    """One-stop endpoint: accept JSON data -> compute -> LLM narrative -> return both.

    Accepts the same AnalysisRequest body as /v1/analysis-jobs/evaluate.
    Returns deterministic computation result + AI narrative in a single response.
    """
    # Step 1: run the deterministic engine (same as evaluate)
    if request.analysis_type is AnalysisType.FINANCIAL_STATEMENT:
        computed = analyze_financial_statement(request)
    elif request.analysis_type is AnalysisType.PRICE_FORECAST:
        computed = forecast_prices(request)
    else:
        computed = analyze_business_metrics(request)

    validated = validate_analysis_response(computed)
    computation = _to_json_value(validated.model_dump())

    # Step 2: run LLM narrative on the computed result
    narrative = narrate(computed)

    return JSONResponse(status_code=200, content={
        "computation": computation,
        "narrative": narrative,
    })


@router.post("/v1/chat")
async def chat_endpoint(request: Request) -> JSONResponse:
    """Natural language chat interface for analysis."""
    payload = await request.json()
    user_message = payload.get("message", "")
    history = payload.get("history", [])
    result = chat_service(user_message, history)
    return JSONResponse(status_code=200, content=result)


def _to_json_value(value: object) -> object:
    if hasattr(value, "model_dump"):
        return _to_json_value(value.model_dump())
    if isinstance(value, dict):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_to_json_value(item) for item in value]
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    return value
