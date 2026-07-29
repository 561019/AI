from fastapi import APIRouter

from app.api.routes import health, intent, intent_analysis


api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(
    intent_analysis.router,
    prefix="/intent-analysis",
    tags=["intent-analysis"],
)
api_router.include_router(intent.router, prefix="/v1/intent", tags=["intent"])
