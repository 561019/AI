from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Callable

import httpx
from fastapi import FastAPI, Header, HTTPException

from .config import Settings
from .models import SearchRequest, SearchResponse
from .runtime import build_service
from .security import PermissionDenied
from .service import SearchService


def create_app(service_factory: Callable[[], SearchService] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service = service_factory() if service_factory else build_service(Settings.from_env())
        app.state.search_service = service
        try:
            yield
        finally:
            service.close()

    app = FastAPI(title="HanHe Search and Rerank", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/search", response_model=SearchResponse)
    def search(
        request: SearchRequest,
        x_actor_id: str = Header(alias="X-Actor-ID"),
    ) -> SearchResponse:
        try:
            return app.state.search_service.search(x_actor_id, request)
        except PermissionDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (httpx.HTTPError, RuntimeError) as exc:
            raise HTTPException(status_code=502, detail=f"search dependency failed: {exc}") from exc

    return app


app = create_app()
