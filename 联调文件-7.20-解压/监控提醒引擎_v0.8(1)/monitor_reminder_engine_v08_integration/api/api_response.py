from datetime import datetime
from typing import Any, Optional


def current_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def success_response(
    data: Any = None,
    message: str = "处理成功",
    request_id: str = "",
    trace_id: str = "",
) -> dict:
    return {
        "code": "0",
        "message": message,
        "request_id": request_id,
        "trace_id": trace_id,
        "data": data if data is not None else {},
        "timestamp": current_time(),
    }


def error_response(
    code: str,
    message: str,
    request_id: str = "",
    trace_id: str = "",
    data: Optional[Any] = None,
) -> dict:
    return {
        "code": code,
        "message": message,
        "request_id": request_id,
        "trace_id": trace_id,
        "data": data if data is not None else {},
        "timestamp": current_time(),
    }
