"""安全中间件 —— 独立模块简化版（默认不做鉴权，方便本地演示）。"""
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


class SecurityAccessMiddleware(BaseHTTPMiddleware):
    """本地演示用：不做鉴权限制，仅透传请求。"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        return await call_next(request)
