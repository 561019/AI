"""安全合规模块 —— 独立运行入口。

启动方式：
    cd 安全合规模块
    python run.py

或：
    uvicorn app.main:app --host 127.0.0.1 --port 8002
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes.security_compliance import router as security_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="1.9 安全合规模块 - 独立版",
    description="运行时安全检查：违规词 → 脱敏 → 权限 → 数据不出域 → 审计留痕",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(security_router)

# 托管前端静态文件
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/frontend", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}
