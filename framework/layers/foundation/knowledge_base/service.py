from __future__ import annotations

import csv
import hashlib
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree

from framework.core import ROOT, standard_response
from framework.envelope import make_internal_envelope
from framework.http import post_json
from framework.module_catalog import MODULE_BY_CODE


MODULE_CODE = "knowledge-base"
MODULE = MODULE_BY_CODE[MODULE_CODE]


def get(handler: Any) -> bool:
    if handler.path == "/api/v1/capabilities":
        handler.send(200, {"items": [{"capability_code": item, "enabled": True} for item in MODULE.capabilities]})
        return True
    return False


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
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    try:
        if capability in {"chunk.split", "vector.index.upsert"}:
            data = _index_uploaded_materials(envelope, payload)
        elif capability in {"knowledge.retrieve", "knowledge.material.get", "search.query", "search.retrieve_context"}:
            data = _retrieve_context(envelope, payload)
        else:
            data = {
                "state": "completed",
                "module": MODULE.code,
                "platform_capability": capability,
                "received_payload": payload,
            }
    except Exception as exc:
        handler.send(500, standard_response(envelope, "failed", error={
            "code": "KNOWLEDGE_BASE_PROCESS_FAILED",
            "message": str(exc),
            "provider_module": MODULE.code,
        }))
        return
    handler.send(200, standard_response(envelope, "success", data=data))


def _index_uploaded_materials(envelope: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    actor = envelope.get("actor") or {}
    timestamp = datetime.now(timezone.utc).isoformat()
    source = payload.get("knowledge_source") if isinstance(payload.get("knowledge_source"), dict) else {}
    uploaded_files = payload.get("uploaded_files") if isinstance(payload.get("uploaded_files"), list) else []
    if not uploaded_files and isinstance(source.get("uploaded_files"), list):
        uploaded_files = source["uploaded_files"]
    if not uploaded_files:
        raise ValueError("uploaded_files is required for knowledge indexing")

    existing_indexes = _find_existing_indexes(envelope, payload, source)
    reusable_files: dict[str, dict[str, Any]] = {}
    for file_item in uploaded_files:
        if not isinstance(file_item, dict):
            continue
        match = _find_index_file_match(file_item, existing_indexes)
        if match:
            reusable_files[_file_key(file_item)] = match
    files_to_index = [
        item for item in uploaded_files
        if isinstance(item, dict) and _file_key(item) not in reusable_files
    ]

    source_id = str(
        payload.get("knowledge_source_id")
        or source.get("knowledge_source_id")
        or payload.get("knowledge_base_id")
        or source.get("knowledge_base_id")
        or f"ks_{uuid4().hex[:16]}"
    )
    knowledge_base_id = str(payload.get("knowledge_base_id") or source.get("knowledge_base_id") or source_id)
    source_record = {
        "knowledge_source_id": source_id,
        "record_id": source_id,
        "tenant_id": actor.get("tenant_id") or source.get("tenant_id") or "web-workbench",
        "owner_account_id": actor.get("user_id") or source.get("owner_account_id") or "anonymous",
        "project_id": source.get("project_id") or payload.get("project_id"),
        "conversation_id": source.get("conversation_id") or payload.get("conversation_id"),
        "knowledge_base_id": knowledge_base_id,
        "knowledge_base_name": payload.get("knowledge_base_name") or source.get("knowledge_base_name"),
        "asset_scope": payload.get("asset_scope") or source.get("asset_scope") or "personal_knowledge",
        "source_type": "uploaded_file",
        "state": "indexed",
        "file_count": len(files_to_index),
        "updated_at": timestamp,
        "source_payload": source or payload,
    }
    if not files_to_index:
        existing = next(iter(reusable_files.values()), {})
        return {
            "state": "reused",
            "module": MODULE.code,
            "platform_capability": "vector.index.upsert",
            "reused": True,
            "knowledge_source_id": existing.get("knowledge_source_id") or source_id,
            "knowledge_base_id": existing.get("knowledge_base_id") or knowledge_base_id,
            "chunk_count": sum(int(item.get("chunk_count") or 0) for item in reusable_files.values()),
            "file_count": len(uploaded_files),
            "file_summaries": [
                summary
                for item in reusable_files.values()
                for summary in (item.get("file_summary") or [],)
                if summary
            ],
            "file_results": [
                {
                    "file_id": file_item.get("file_id") or file_item.get("object_id"),
                    "state": "reused",
                    "knowledge_source_id": match.get("knowledge_source_id"),
                    "knowledge_base_id": match.get("knowledge_base_id") or knowledge_base_id,
                    "chunk_count": match.get("chunk_count", 0),
                }
                for file_item in uploaded_files
                if isinstance(file_item, dict)
                for match in [reusable_files.get(_file_key(file_item), {})]
            ],
            "datasets": ["knowledge_chunks", "knowledge_indexes"],
        }
    chunks: list[dict[str, Any]] = []
    file_summaries: list[dict[str, Any]] = []
    for file_index, file_item in enumerate(files_to_index, start=1):
        if not isinstance(file_item, dict):
            continue
        text = _extract_file_text(file_item)
        file_chunks = _split_text(text, max_chars=1200)
        file_id = str(file_item.get("file_id") or file_item.get("object_id") or f"file-{file_index}")
        file_summaries.append({
            "file_id": file_id,
            "original_name": file_item.get("original_name") or file_item.get("original_filename") or file_item.get("name"),
            "chunk_count": len(file_chunks),
            "size_bytes": file_item.get("size_bytes"),
            "sha256": file_item.get("sha256"),
        })
        for chunk_index, chunk_text in enumerate(file_chunks, start=1):
            chunk_id = f"kchk_{hashlib.sha1(f'{source_id}:{file_id}:{chunk_index}'.encode('utf-8')).hexdigest()[:24]}"
            chunks.append({
                "chunk_id": chunk_id,
                "record_id": chunk_id,
                "knowledge_source_id": source_id,
                "knowledge_base_id": knowledge_base_id,
                "tenant_id": source_record["tenant_id"],
                "owner_account_id": source_record["owner_account_id"],
                "project_id": source_record.get("project_id"),
                "conversation_id": source_record.get("conversation_id"),
                "asset_scope": source_record["asset_scope"],
                "file_id": file_id,
                "object_id": file_item.get("object_id"),
                "original_name": file_item.get("original_name") or file_item.get("original_filename") or file_item.get("name"),
                "chunk_index": chunk_index,
                "content": chunk_text,
                "content_preview": chunk_text[:240],
                "keywords": _keywords(chunk_text),
                "parse_engine": MODULE_CODE,
                "parse_state": "completed",
                "created_at": timestamp,
                "updated_at": timestamp,
            })
    index_id = f"kidx_{hashlib.sha1(source_id.encode('utf-8')).hexdigest()[:24]}"
    index_record = {
        "index_id": index_id,
        "record_id": index_id,
        "knowledge_source_id": source_id,
        "knowledge_base_id": knowledge_base_id,
        "tenant_id": source_record["tenant_id"],
        "owner_account_id": source_record["owner_account_id"],
        "project_id": source_record.get("project_id"),
        "conversation_id": source_record.get("conversation_id"),
        "asset_scope": source_record["asset_scope"],
        "state": "indexed",
        "chunk_count": len(chunks),
        "file_summaries": file_summaries,
        "index_backend": "local_keyword_chunks",
        "updated_at": timestamp,
    }
    storage = _foundation_write(envelope, [
        {"dataset": "knowledge_sources", "operation": "upsert", "records": [source_record]},
        {"dataset": "knowledge_chunks", "operation": "upsert", "records": chunks} if chunks else None,
        {"dataset": "knowledge_indexes", "operation": "upsert", "records": [index_record]},
    ])
    return {
        "state": "indexed",
        "module": MODULE.code,
        "platform_capability": "vector.index.upsert",
        "knowledge_source_id": source_id,
        "knowledge_base_id": knowledge_base_id,
        "chunk_count": len(chunks),
        "file_count": len(files_to_index),
        "file_summaries": file_summaries,
        "file_results": [
            *[
                {
                    "file_id": file_item.get("file_id") or file_item.get("object_id"),
                    "state": "reused",
                    "knowledge_source_id": match.get("knowledge_source_id"),
                    "knowledge_base_id": match.get("knowledge_base_id") or knowledge_base_id,
                    "chunk_count": match.get("chunk_count", 0),
                }
                for file_item in uploaded_files
                if isinstance(file_item, dict)
                for match in [reusable_files.get(_file_key(file_item))]
                if match
            ],
            *[
                {
                    "file_id": summary.get("file_id"),
                    "state": "indexed",
                    "knowledge_source_id": source_id,
                    "knowledge_base_id": knowledge_base_id,
                    "chunk_count": summary.get("chunk_count", 0),
                }
                for summary in file_summaries
            ],
        ],
        "storage_result": storage,
        "datasets": ["knowledge_sources", "knowledge_chunks", "knowledge_indexes"],
    }


def _find_existing_indexes(envelope: dict[str, Any], payload: dict[str, Any], source: dict[str, Any]) -> list[dict[str, Any]]:
    actor = envelope.get("actor") if isinstance(envelope.get("actor"), dict) else {}
    knowledge_base_id = payload.get("knowledge_base_id") or source.get("knowledge_base_id")
    filters = {
        "owner_account_id": actor.get("user_id") or source.get("owner_account_id"),
        "knowledge_base_id": knowledge_base_id,
        "asset_scope": payload.get("asset_scope") or source.get("asset_scope") or "personal_knowledge",
        "state": "indexed",
    }
    filters = {key: value for key, value in filters.items() if value not in (None, "")}
    try:
        result = _foundation_query(envelope, "knowledge_indexes", filters, 500)
    except RuntimeError:
        return []
    items = result.get("items") if isinstance(result.get("items"), list) else []
    return [item for item in items if isinstance(item, dict)]


def _find_index_file_match(file_item: dict[str, Any], indexes: list[dict[str, Any]]) -> dict[str, Any] | None:
    file_id = str(file_item.get("file_id") or file_item.get("object_id") or "")
    sha256 = str(file_item.get("sha256") or "")
    for index in indexes:
        summaries = index.get("file_summaries") if isinstance(index.get("file_summaries"), list) else []
        for summary in summaries:
            if not isinstance(summary, dict):
                continue
            if (sha256 and str(summary.get("sha256") or "") == sha256) or (
                file_id and str(summary.get("file_id") or "") == file_id
            ):
                return {
                    "knowledge_source_id": index.get("knowledge_source_id"),
                    "knowledge_base_id": index.get("knowledge_base_id"),
                    "chunk_count": summary.get("chunk_count", 0),
                    "file_summary": summary,
                }
    return None


def _file_key(file_item: dict[str, Any]) -> str:
    return str(file_item.get("sha256") or file_item.get("file_id") or file_item.get("object_id") or "")


def _retrieve_context(envelope: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or payload.get("question") or payload.get("utterance") or payload.get("semantic_query") or "").strip()
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    if payload.get("knowledge_base_id"):
        filters = {**filters, "knowledge_base_id": payload.get("knowledge_base_id")}
    if payload.get("asset_scope"):
        filters = {**filters, "asset_scope": payload.get("asset_scope")}
    actor = envelope.get("actor") if isinstance(envelope.get("actor"), dict) else {}
    if filters.get("asset_scope") == "personal_knowledge" and not filters.get("owner_account_id") and actor.get("user_id"):
        filters = {**filters, "owner_account_id": actor.get("user_id")}
    result = _foundation_query(envelope, "knowledge_chunks", filters, int(payload.get("limit") or 20))
    items = result.get("items") if isinstance(result.get("items"), list) else []
    ranked = sorted(items, key=lambda item: _score_chunk(item, query), reverse=True)
    if query:
        ranked = [item for item in ranked if _score_chunk(item, query) > 0] or ranked
    contexts = ranked[: int(payload.get("top_k") or 5)]
    return {
        "state": "completed",
        "module": MODULE.code,
        "platform_capability": payload.get("action") or "knowledge.retrieve",
        "query": query,
        "count": len(contexts),
        "items": contexts,
        "source_dataset": "knowledge_chunks",
    }


def _extract_file_text(file_item: dict[str, Any]) -> str:
    path = _resolve_file_path(file_item)
    if not path or not path.exists():
        return ""
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".csv"}:
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="ignore")
        if suffix == ".csv":
            return _csv_text(text)
        return text
    if suffix in {".xlsx", ".xlsm"}:
        return _xlsx_text(path)
    if suffix == ".docx":
        return _docx_text(path)
    return path.read_bytes().decode("utf-8", errors="ignore")


def _resolve_file_path(file_item: dict[str, Any]) -> Path | None:
    for key in ("saved_path", "path"):
        if file_item.get(key):
            return Path(str(file_item[key]))
    storage_uri = str(file_item.get("storage_uri") or "")
    if storage_uri.startswith("local://framework/"):
        return ROOT / storage_uri.removeprefix("local://framework/")
    stored_name = file_item.get("stored_name")
    if stored_name:
        return ROOT / "data" / "foundation_data" / "objects" / "uploads" / str(stored_name)
    return None


def _csv_text(text: str) -> str:
    rows = []
    for index, row in enumerate(csv.reader(text.splitlines()), start=1):
        rows.append(f"第{index}行：" + " | ".join(str(cell) for cell in row))
        if index >= 2000:
            break
    return "\n".join(rows)


def _xlsx_text(path: Path) -> str:
    try:
        import openpyxl
    except Exception:
        return ""
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    lines: list[str] = []
    for sheet in workbook.worksheets:
        lines.append(f"工作表：{sheet.title}")
        for row_index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            values = ["" if value is None else str(value) for value in row]
            if any(values):
                lines.append(f"{sheet.title} 第{row_index}行：" + " | ".join(values))
            if row_index >= 2000:
                lines.append(f"{sheet.title} 后续行已省略")
                break
    return "\n".join(lines)


def _docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as package:
            xml = package.read("word/document.xml")
    except Exception:
        return ""
    root = ElementTree.fromstring(xml)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []
    for paragraph in root.findall(".//w:p", namespace):
        texts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
        line = "".join(texts).strip()
        if line:
            paragraphs.append(line)
    return "\n".join(paragraphs)


def _split_text(text: str, *, max_chars: int) -> list[str]:
    normalized = "\n".join(line.strip() for line in str(text or "").splitlines() if line.strip())
    if not normalized:
        return []
    chunks: list[str] = []
    current = ""
    for line in normalized.splitlines():
        if len(current) + len(line) + 1 > max_chars and current:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}".strip()
    if current:
        chunks.append(current)
    return chunks[:500]


def _keywords(text: str) -> list[str]:
    tokens = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9_-]{2,}", str(text or ""))
    seen: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
        if len(seen) >= 30:
            break
    return seen


def _score_chunk(item: dict[str, Any], query: str) -> int:
    if not query:
        return 1
    content = str(item.get("content") or "")
    keywords = item.get("keywords") if isinstance(item.get("keywords"), list) else []
    score = 0
    for token in _keywords(query):
        if token in content:
            score += 5
        if token in keywords:
            score += 3
    return score


def _foundation_write(envelope: dict[str, Any], writes: list[dict[str, Any] | None]) -> dict[str, Any]:
    payload = {"writes": [item for item in writes if item and item.get("records")]}
    inner = make_internal_envelope(
        envelope.get("trace_id"),
        envelope.get("actor") or {"tenant_id": "web-workbench", "user_id": "system", "authenticated": True},
        str((envelope.get("payload") or {}).get("platform_task_id") or envelope.get("request_id") or uuid4()),
        "foundation_data.write",
        "foundation",
        "foundation-data",
        payload,
        source_layer="foundation",
        source_module=MODULE_CODE,
        context=envelope.get("context") if isinstance(envelope.get("context"), dict) else {},
    )
    status, response = post_json(
        "http://127.0.0.1:8300/api/v1/foundation/instructions",
        inner,
        timeout=120,
        caller={"layer": "foundation", "module": MODULE_CODE},
    )
    if status not in {200, 202} or not isinstance(response, dict) or response.get("status") != "success":
        raise RuntimeError(str(response))
    return response.get("data") or {}


def _foundation_query(envelope: dict[str, Any], dataset: str, filters: dict[str, Any], limit: int) -> dict[str, Any]:
    inner = make_internal_envelope(
        envelope.get("trace_id"),
        envelope.get("actor") or {"tenant_id": "web-workbench", "user_id": "system", "authenticated": True},
        str((envelope.get("payload") or {}).get("platform_task_id") or envelope.get("request_id") or uuid4()),
        "foundation_data.query",
        "foundation",
        "foundation-data",
        {"dataset": dataset, "filters": filters, "limit": limit},
        source_layer="foundation",
        source_module=MODULE_CODE,
        context=envelope.get("context") if isinstance(envelope.get("context"), dict) else {},
    )
    status, response = post_json(
        "http://127.0.0.1:8300/api/v1/foundation/instructions",
        inner,
        timeout=60,
        caller={"layer": "foundation", "module": MODULE_CODE},
    )
    if status not in {200, 202} or not isinstance(response, dict) or response.get("status") != "success":
        raise RuntimeError(str(response))
    return response.get("data") or {}
