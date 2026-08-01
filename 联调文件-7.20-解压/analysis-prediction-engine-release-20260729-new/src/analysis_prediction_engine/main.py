# ---- load .env BEFORE any other imports (module-level constants read env at import time) ----
import os as _os

_env_dir = _os.path.dirname(_os.path.abspath(__file__))
_env_path = _os.path.join(_env_dir, "..", "..", ".env")
_env_path = _os.path.normpath(_env_path)
if _os.path.exists(_env_path):
    with open(_env_path, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _sep, _val = _line.partition("=")
                _os.environ.setdefault(_key.strip(), _val.strip())
# -----------------------------------------------------------------

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from analysis_prediction_engine.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        payload = exc.body if isinstance(exc.body, dict) else None
        trace_id = payload.get("trace_id") if payload is not None else None
        error = {
            "code": "VALIDATION_ERROR",
            "message": "request validation failed",
        }
        if isinstance(trace_id, str) and trace_id.strip():
            error = {
                "schema_version": "v1",
                "trace_id": trace_id.strip(),
                **error,
            }
        return JSONResponse(status_code=422, content=error)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "analysis-prediction-engine",
        }

    app.include_router(router)
    return app


app = create_app()
