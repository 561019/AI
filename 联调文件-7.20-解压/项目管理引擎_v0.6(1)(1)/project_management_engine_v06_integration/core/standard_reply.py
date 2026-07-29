from __future__ import annotations

from typing import Any


def success(*, trace_id: str, data: Any = None, message: str = "办理成功", http_status: int = 200) -> dict:
    return {"reply_type":"success","trace_id":trace_id,"message":message,"data":data,"error":None,"governance":None,"_http_status":http_status}


def accepted(*, trace_id: str, data: Any = None, message: str = "已受理", http_status: int = 202) -> dict:
    return {"reply_type":"accepted","trace_id":trace_id,"message":message,"data":data,"error":None,"governance":None,"_http_status":http_status}


def failed(*, trace_id: str, code: str, message: str, retryable: bool=False, http_status: int=400) -> dict:
    return {"reply_type":"failed","trace_id":trace_id,"message":message,"data":None,"error":{"code":code,"message":message,"retryable":retryable},"governance":None,"_http_status":http_status}


def with_governance(reply: dict, governance: dict) -> dict:
    result = dict(reply)
    result["governance"] = governance
    return result


def public_reply(reply: dict) -> dict:
    result = dict(reply)
    result.pop("_http_status", None)
    return result
