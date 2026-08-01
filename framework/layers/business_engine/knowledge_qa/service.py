from __future__ import annotations

from typing import Any
from uuid import uuid4

from framework.core import standard_response
from framework.envelope import make_internal_envelope
from framework.http import post_json
from framework.layers.business_engine.generic_module_adapter import get_for
from framework.module_catalog import MODULE_BY_CODE

MODULE_CODE = "knowledge-qa"
MODULE = MODULE_BY_CODE[MODULE_CODE]


def get(handler):
    return get_for(MODULE_CODE, handler)


def post(handler: Any, envelope: dict[str, Any]) -> None:
    if handler.path != MODULE.interface:
        handler.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}})
        return
    capability = envelope.get("target", {}).get("capability") or envelope.get("action")
    if capability not in MODULE.capabilities:
        handler.send(422, standard_response(envelope, "failed", error={
            "code": "CAPABILITY_NOT_SUPPORTED_BY_MODULE",
            "capability": capability,
            "provider_module": MODULE.code,
        }))
        return
    try:
        data = _answer_from_knowledge_base(envelope, capability)
    except RuntimeError as exc:
        handler.send(502, standard_response(envelope, "failed", error={
            "code": "KNOWLEDGE_QA_RETRIEVAL_FAILED",
            "message": str(exc),
        }))
        return
    handler.send(200, standard_response(envelope, "success", data=data))


def _answer_from_knowledge_base(envelope: dict[str, Any], capability: str) -> dict[str, Any]:
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    query = str(
        payload.get("query")
        or payload.get("question")
        or payload.get("utterance")
        or payload.get("user_goal")
        or payload.get("analysis_goal")
        or ""
    ).strip()
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    for key in ("knowledge_base_id", "asset_scope", "owner_account_id", "project_id", "conversation_id"):
        if payload.get(key):
            filters[key] = payload.get(key)
    actor = envelope.get("actor") if isinstance(envelope.get("actor"), dict) else {}
    if not filters.get("owner_account_id") and actor.get("user_id"):
        filters["owner_account_id"] = actor.get("user_id")
    uploaded_documents = payload.get("uploaded_documents") if isinstance(payload.get("uploaded_documents"), list) else []
    file_ids = [str(item.get("file_id")) for item in uploaded_documents if isinstance(item, dict) and item.get("file_id")]
    if file_ids:
        filters["file_id"] = file_ids
    retrieval = _knowledge_retrieve(envelope, query, filters)
    items = retrieval.get("items") if isinstance(retrieval.get("items"), list) else []
    if not items:
        answer = "当前知识库中没有检索到可支撑回答的已解析内容。请确认文件已上传到知识库并完成解析入库。"
    else:
        answer = _build_answer(query, items)
    return {
        "state": "completed",
        "module": MODULE.code,
        "module_name_cn": MODULE.name_cn,
        "platform_capability": capability,
        "query": query,
        "answer": answer,
        "user_answer": answer,
        "summary": answer,
        "knowledge_context": {
            "source_dataset": retrieval.get("source_dataset") or "knowledge_chunks",
            "count": len(items),
            "items": items,
        },
        "evidence": [
            {
                "knowledge_source_id": item.get("knowledge_source_id"),
                "file_id": item.get("file_id"),
                "original_name": item.get("original_name"),
                "chunk_index": item.get("chunk_index"),
            }
            for item in items[:5]
        ],
    }


def _knowledge_retrieve(envelope: dict[str, Any], query: str, filters: dict[str, Any]) -> dict[str, Any]:
    inner = make_internal_envelope(
        envelope.get("trace_id"),
        envelope.get("actor") or {"tenant_id": "web-workbench", "user_id": "system", "authenticated": True},
        str((envelope.get("payload") or {}).get("platform_task_id") or envelope.get("request_id") or uuid4()),
        "knowledge.retrieve",
        "foundation",
        "foundation-gateway",
        {"query": query, "filters": filters, "limit": 50, "top_k": 5},
        source_layer="business_engine",
        source_module=MODULE_CODE,
        context=envelope.get("context") if isinstance(envelope.get("context"), dict) else {},
    )
    status, response = post_json(
        "http://127.0.0.1:8300/api/v1/foundation/instructions",
        inner,
        timeout=60,
        caller={"layer": "business_engine", "module": MODULE_CODE},
    )
    if status not in {200, 202} or not isinstance(response, dict) or response.get("status") != "success":
        raise RuntimeError(str(response))
    return response.get("data") or {}


def _build_answer(query: str, items: list[dict[str, Any]]) -> str:
    lines = ["我已从知识库已解析内容中找到相关资料："]
    for index, item in enumerate(items[:3], start=1):
        name = item.get("original_name") or item.get("file_id") or "知识材料"
        preview = str(item.get("content_preview") or item.get("content") or "").strip()
        if len(preview) > 220:
            preview = preview[:220] + "..."
        lines.append(f"{index}. {name}：{preview}")
    if query:
        lines.append("以上内容来自知识库模块解析后的结果，可继续交给内容产出或流程执行模块形成正式回答。")
    return "\n".join(lines)
