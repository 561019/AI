from __future__ import annotations
import json,os
from time import perf_counter
from typing import Any
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen
from uuid import uuid4
from framework.core import record_interface_call

def post(handler:Any,payload:dict[str,Any])->None:
    if handler.path!="/api/v1/models/responses": handler.send(404); return
    missing=[key for key in ("trace_id","actor","task_type","messages","model_policy") if key not in payload]
    if missing: handler.send(400,{"error":{"code":"INVALID_MODEL_REQUEST","message":f"缺少字段: {missing}"}}); return
    try: result=dispatch(payload)
    except HTTPError as exc:
        raw=exc.read().decode("utf-8",errors="replace")
        try: detail=json.loads(raw)
        except json.JSONDecodeError: detail=raw
        handler.send(502,{"error":{"code":"MODEL_PROVIDER_ERROR","message":f"DeepSeek HTTP {exc.code}","provider_error":detail}}); return
    except (URLError,TimeoutError,ValueError,json.JSONDecodeError) as exc: handler.send(502,{"error":{"code":"MODEL_PROVIDER_ERROR","message":str(exc)}}); return
    handler.send(200,result)

def dispatch(payload:dict[str,Any])->dict[str,Any]:
    api_key=os.getenv("DEEPSEEK_API_KEY","").strip()
    if not api_key: return _mock(payload)
    base=os.getenv("DEEPSEEK_BASE_URL","https://api.deepseek.com").rstrip("/"); model=os.getenv("DEEPSEEK_MODEL","deepseek-chat"); policy=payload.get("model_policy",{})
    provider_payload={"model":model,"messages":payload["messages"],"temperature":policy.get("temperature",.1),"max_tokens":policy.get("max_output_tokens",500),"response_format":{"type":"json_object"}}
    request=Request(f"{base}/chat/completions",data=json.dumps(provider_payload,ensure_ascii=False).encode("utf-8"),headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"},method="POST"); started=perf_counter()
    with urlopen(request,timeout=float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS","30"))) as response: provider=json.loads(response.read().decode("utf-8"))
    content=provider["choices"][0]["message"]["content"].strip()
    if content.startswith("```"): content=content.split("\n",1)[1].rsplit("```",1)[0].strip()
    usage=provider.get("usage",{}); result={"trace_id":payload["trace_id"],"model_call_id":provider.get("id",str(uuid4())),"provider":"deepseek","model":provider.get("model",model),"output":json.loads(content),"usage":{"input_tokens":usage.get("prompt_tokens",0),"output_tokens":usage.get("completion_tokens",0),"estimated_cost":0},"fallback_used":False}
    record_interface_call(trace_id=payload["trace_id"],source={"layer":"foundation","module":"model-dispatcher"},target={"layer":"external_provider","module":"deepseek"},capability="model.chat.completions",method="POST",url=f"{base}/chat/completions",request=provider_payload,response=result,status_code=200,duration_ms=(perf_counter()-started)*1000); return result

def _mock(payload:dict[str,Any])->dict[str,Any]:
    text=next((str(item.get("content","")) for item in reversed(payload.get("messages",[])) if item.get("role")=="user"),""); capability="rule.calculate" if any(word in text for word in ("计算","提成","金额","比例")) else "knowledge.answer"
    import re
    values=[float(value) for value in re.findall(r"(?<![\w.])\d+(?:\.\d+)?",text)]
    return {"trace_id":payload["trace_id"],"model_call_id":f"mock-{uuid4()}","provider":"local-mock","model":"mock-intent-model","output":{"capability_code":capability,"description":text,"confidence":.92,"clarification_required":False,"parameters":{"values":values}},"usage":{"input_tokens":0,"output_tokens":0,"estimated_cost":0},"fallback_used":True}
