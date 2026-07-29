from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine


router = APIRouter()


@router.get("")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
    }


@router.get("/ready", response_model=None)
def readiness_check() -> Any:
    checks = {
        "database": _check_database(),
        "milvus": _check_milvus(),
    }
    is_ready = all(item["status"] == "ok" for item in checks.values())
    payload = {
        **health_check(),
        "status": "ok" if is_ready else "degraded",
        "checks": checks,
    }

    if not is_ready:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload,
        )

    return payload


def _check_database() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as error:
        return {
            "status": "error",
            "message": str(error),
        }

    return {"status": "ok"}


def _check_milvus() -> dict[str, str]:
    alias = "healthcheck"
    try:
        from pymilvus import connections, utility

        connections.connect(
            alias=alias,
            host=settings.milvus_host,
            port=str(settings.milvus_port),
        )
        version = utility.get_server_version(using=alias)
    except Exception as error:
        return {
            "status": "error",
            "message": str(error),
        }
    finally:
        try:
            from pymilvus import connections

            connections.disconnect(alias)
        except Exception:
            pass

    return {
        "status": "ok",
        "version": version,
    }
