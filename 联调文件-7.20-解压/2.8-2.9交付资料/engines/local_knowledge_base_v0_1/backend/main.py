from __future__ import annotations

from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .kb_engine import (
    TASK_PROFILES,
    USERS,
    append_log,
    get_item,
    get_task_materials,
    read_items,
    read_logs,
    search_items,
    write_items,
)
from .models import ItemCreateRequest, SearchRequest, TaskMaterialRequest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

app = FastAPI(title="本地知识库 v0.1 临时接口版", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "module": "L1-1.13 本地知识库",
        "prototype": "v0.1 临时接口版",
        "note": "本版本用于验证本地取素材/模板/依据资料，不代表正式 1.13 接口字段。",
    }


@app.get("/api/bootstrap")
def bootstrap():
    items = read_items()
    types = sorted({x["type"] for x in items})
    tags = sorted({tag for item in items for tag in item.get("tags", [])})
    return {
        "users": USERS,
        "task_profiles": TASK_PROFILES,
        "types": types,
        "tags": tags,
        "item_count": len(items),
        "interfaces": [
            {"method": "POST", "path": "/api/kb/search", "purpose": "按问题检索资料，返回带出处片段"},
            {"method": "GET", "path": "/api/kb/materials/{material_id}", "purpose": "按资料 ID 读取单条资料"},
            {"method": "GET", "path": "/api/kb/templates/{template_id}", "purpose": "按模板 ID 读取模板"},
            {"method": "POST", "path": "/api/kb/task-materials", "purpose": "按任务类型取一组素材/模板/依据资料"},
        ],
    }


@app.get("/api/kb/items")
def list_items(actor_id: str = Query("U001")):
    results = []
    for item in read_items():
        try:
            results.append(get_item(actor_id, item["material_id"]))
        except PermissionError:
            continue
    return {"actor_id": actor_id, "count": len(results), "items": results}


@app.post("/api/kb/search")
def search(req: SearchRequest):
    if req.actor_id not in USERS:
        raise HTTPException(status_code=400, detail={"code": "KB_400_UNKNOWN_ACTOR", "message": "未知真人/演示用户"})
    return search_items(req.actor_id, req.query, req.top_k, req.types, req.tags)


@app.get("/api/kb/materials/{material_id}")
def material_detail(material_id: str, actor_id: str = Query("U001")):
    try:
        return get_item(actor_id, material_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"code": "KB_403_PERMISSION_DENIED", "message": str(exc)})
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "KB_404_NOT_FOUND", "message": "资料不存在"})


@app.get("/api/kb/templates/{template_id}")
def template_detail(template_id: str, actor_id: str = Query("U001")):
    try:
        item = get_item(actor_id, template_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"code": "KB_403_PERMISSION_DENIED", "message": str(exc)})
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "KB_404_NOT_FOUND", "message": "模板不存在"})
    if item["type"] != "template":
        raise HTTPException(status_code=400, detail={"code": "KB_400_NOT_TEMPLATE", "message": "该资料不是模板类型"})
    return item


@app.post("/api/kb/task-materials")
def task_materials(req: TaskMaterialRequest):
    if req.actor_id not in USERS:
        raise HTTPException(status_code=400, detail={"code": "KB_400_UNKNOWN_ACTOR", "message": "未知真人/演示用户"})
    try:
        return get_task_materials(req.actor_id, req.task_type, req.query, req.top_k, req.include_templates)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "KB_404_TASK_PROFILE", "message": "任务类型不存在"})


@app.get("/api/kb/logs")
def logs():
    return read_logs()


@app.post("/api/kb/items")
def create_item(req: ItemCreateRequest):
    items = read_items()
    if any(x["material_id"] == req.material_id for x in items):
        raise HTTPException(status_code=409, detail={"code": "KB_409_DUPLICATE_ID", "message": "资料 ID 已存在"})
    item = req.model_dump() if hasattr(req, "model_dump") else req.dict()
    items.append(item)
    write_items(items)
    append_log({
        "time": item["updated_at"],
        "query_id": "ITEM-CREATE",
        "actor_id": "system",
        "query": req.material_id,
        "returned_count": 1,
        "readiness": "created",
    })
    return item
