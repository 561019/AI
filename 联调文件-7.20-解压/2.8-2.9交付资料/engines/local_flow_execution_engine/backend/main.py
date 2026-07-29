from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import ROOT, read_env, save_env
from .models import ConfigUpdateRequest, FlowCallbackRequest, FlowStartRequest, HumanDecisionRequest
from .workflow import apply_flow_callback, capabilities, decide_human, get_instance, health, list_instances, reset_instances, start_flow


FRONTEND = ROOT / "frontend"

app = FastAPI(title="本地简化流程执行引擎", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/health")
def health_check():
    return health()


@app.get("/api/v1/capabilities")
def api_capabilities():
    return capabilities()


@app.get("/api/config")
def config():
    values = read_env()
    return {
        "media_base": values["MEDIA_BASE"],
        "content_base": values["CONTENT_BASE"],
        "request_timeout_seconds": int(values["REQUEST_TIMEOUT_SECONDS"]),
    }


@app.post("/api/config")
def update_config(req: ConfigUpdateRequest):
    payload = req.model_dump() if hasattr(req, "model_dump") else req.dict()
    values = save_env(payload)
    return {
        "media_base": values["MEDIA_BASE"],
        "content_base": values["CONTENT_BASE"],
        "request_timeout_seconds": int(values["REQUEST_TIMEOUT_SECONDS"]),
    }


@app.post("/api/flow/start")
def api_flow_start(req: FlowStartRequest):
    try:
        return start_flow(req)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/flow/list")
def api_flow_list():
    return list_instances()


@app.get("/api/flow/{instance_id}")
def api_flow_get(instance_id: str):
    try:
        return get_instance(instance_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="流程实例不存在") from exc


@app.post("/api/flow/decide")
def api_flow_decide(req: HumanDecisionRequest):
    try:
        return decide_human(req)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/flow/callback")
def api_flow_callback(req: FlowCallbackRequest):
    try:
        return apply_flow_callback(req)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/reset")
def api_reset():
    return reset_instances()
