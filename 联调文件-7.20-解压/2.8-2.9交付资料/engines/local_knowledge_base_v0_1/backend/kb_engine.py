from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import json
import re
import uuid

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
ITEMS_PATH = DATA_DIR / "kb_items.json"
LOG_PATH = DATA_DIR / "query_logs.json"

USERS = {
    "U001": {
        "real_person_id": "RP-0001",
        "name": "张三",
        "position": "产品推广专员",
        "permission_scopes": ["产品推广部"],
    },
    "U002": {
        "real_person_id": "RP-0002",
        "name": "李四",
        "position": "品牌负责人",
        "permission_scopes": ["产品推广部", "品牌负责人"],
    },
    "U003": {
        "real_person_id": "RP-0003",
        "name": "王五",
        "position": "安全管理人员",
        "permission_scopes": ["生产一部", "安全管理人员"],
    },
    "U004": {
        "real_person_id": "RP-0004",
        "name": "赵六",
        "position": "安全审计员",
        "permission_scopes": ["集团审计"],
    },
    "U005": {
        "real_person_id": "RP-0005",
        "name": "陈律师",
        "position": "律师",
        "permission_scopes": ["法律服务行业/诉讼团队", "律师"],
    },
}

TASK_PROFILES = {
    "marketing_bundle": {
        "name": "内容产出：营销文案组合",
        "query_hint": "智能监测设备 营销文案 品牌规范 模板",
        "required_types": ["product_profile", "style_guide", "template", "compliance_rule"],
        "preferred_ids": ["MAT-PRODUCT-001", "MAT-BRAND-001", "TPL-MARKETING-BUNDLE", "MAT-COMPLIANCE-WORDS-001"],
    },
    "rectification_notice": {
        "name": "内容产出：整改通知书",
        "query_hint": "隐患 整改通知书 消防通道 法规 模板",
        "required_types": ["business_fact", "regulation", "template"],
        "preferred_ids": ["MAT-HAZARD-001", "MAT-SAFETY-LAW-001", "TPL-RECTIFICATION-NOTICE"],
    },
    "legal_pleading": {
        "name": "内容产出：法律文书草稿",
        "query_hint": "买卖合同 诉状 法律文书 草稿 模板",
        "required_types": ["case_fact", "legal_structure", "template"],
        "preferred_ids": ["MAT-CASE-FACT-001", "MAT-LEGAL-STRUCTURE-001", "TPL-LEGAL-PLEADING"],
    },
    "multimedia_poster": {
        "name": "多媒体生成：海报素材取材",
        "query_hint": "智能监测设备 海报 Logo 产品图 爆款案例 品牌规范",
        "required_types": ["product_profile", "style_guide", "media_asset", "hot_case", "compliance_rule"],
        "preferred_ids": ["MAT-PRODUCT-001", "MAT-BRAND-001", "MAT-LOGO-001", "MAT-PRODUCT-IMAGE-001", "MAT-HOT-CASE-001", "MAT-COMPLIANCE-WORDS-001"],
    },
    "hot_case_reuse": {
        "name": "多媒体生成：爆款案例复用取材",
        "query_hint": "智能监测设备 爆款原件 拆解记录 爆款模式 制作标准 高转化 海报 复用 品牌规范 产品图 合规",
        "required_types": ["hot_case_original", "hot_case_breakdown", "hot_case", "product_profile", "style_guide", "media_asset", "compliance_rule"],
        "preferred_ids": [
            "MAT-HOT-CASE-ORIGINAL-001",
            "MAT-HOT-CASE-BREAKDOWN-001",
            "MAT-HOT-CASE-001",
            "MAT-PRODUCT-001",
            "MAT-BRAND-001",
            "MAT-LOGO-001",
            "MAT-PRODUCT-IMAGE-001",
            "MAT-COMPLIANCE-WORDS-001",
        ],
    },
    "product_video": {
        "name": "多媒体生成：产品视频素材取材",
        "query_hint": "智能监测设备 产品视频 产品资料 品牌规范 产品图 合规",
        "required_types": ["product_profile", "style_guide", "media_asset", "compliance_rule"],
        "preferred_ids": ["MAT-PRODUCT-001", "MAT-BRAND-001", "MAT-PRODUCT-IMAGE-001", "MAT-LOGO-001", "MAT-COMPLIANCE-WORDS-001"],
    },
    "video_editing": {
        "name": "多媒体生成：视频剪接素材取材",
        "query_hint": "智能监测设备 视频剪接 产品素材 品牌规范 字幕 合规",
        "required_types": ["product_profile", "style_guide", "media_asset", "compliance_rule"],
        "preferred_ids": ["MAT-PRODUCT-001", "MAT-BRAND-001", "MAT-PRODUCT-IMAGE-001", "MAT-LOGO-001", "MAT-COMPLIANCE-WORDS-001"],
    },
    "fixed_short_video": {
        "name": "多媒体生成：固定类别短视频素材取材",
        "query_hint": "智能监测设备 固定短视频 商品成片 课件转视频 产品图 品牌规范 合规",
        "required_types": ["product_profile", "style_guide", "media_asset", "hot_case", "compliance_rule"],
        "preferred_ids": ["MAT-PRODUCT-001", "MAT-BRAND-001", "MAT-PRODUCT-IMAGE-001", "MAT-LOGO-001", "MAT-HOT-CASE-001", "MAT-COMPLIANCE-WORDS-001"],
    },
    "text_to_speech": {
        "name": "多媒体生成：文字转语音素材取材",
        "query_hint": "智能监测设备 口播 语音 合规 品牌表达 产品说明",
        "required_types": ["product_profile", "style_guide", "compliance_rule"],
        "preferred_ids": ["MAT-PRODUCT-001", "MAT-BRAND-001", "MAT-COMPLIANCE-WORDS-001"],
    },
    "media_processing": {
        "name": "多媒体生成：音画合成与媒体处理素材取材",
        "query_hint": "智能监测设备 音画合成 字幕 格式转换 产品素材 品牌规范 合规",
        "required_types": ["product_profile", "style_guide", "media_asset", "compliance_rule"],
        "preferred_ids": ["MAT-PRODUCT-001", "MAT-BRAND-001", "MAT-PRODUCT-IMAGE-001", "MAT-LOGO-001", "MAT-COMPLIANCE-WORDS-001"],
    },
}


def ensure_files() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if not LOG_PATH.exists():
        LOG_PATH.write_text("[]", encoding="utf-8")


def read_items() -> list[dict[str, Any]]:
    ensure_files()
    return json.loads(ITEMS_PATH.read_text(encoding="utf-8"))


def write_items(items: list[dict[str, Any]]) -> None:
    ITEMS_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def read_logs() -> list[dict[str, Any]]:
    ensure_files()
    return json.loads(LOG_PATH.read_text(encoding="utf-8-sig"))


def append_log(record: dict[str, Any]) -> None:
    logs = read_logs()
    logs.append(record)
    LOG_PATH.write_text(json.dumps(logs[-500:], ensure_ascii=False, indent=2), encoding="utf-8")


def get_user(actor_id: str) -> dict[str, Any] | None:
    return USERS.get(actor_id)


def can_read(actor_id: str, item: dict[str, Any]) -> bool:
    user = get_user(actor_id)
    if not user:
        return False
    scopes = set(user["permission_scopes"])
    item_scopes = set(item.get("permission_scope", []))
    return "public" in item_scopes or bool(scopes & item_scopes)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def query_tokens(query: str) -> list[str]:
    query = normalize(query)
    words = [x for x in re.split(r"[\s,，。；;、/]+", query) if x]
    chars = [x for x in query if "\u4e00" <= x <= "\u9fff"]
    return list(dict.fromkeys(words + chars))


def score_item(item: dict[str, Any], query: str, tags: list[str] | None = None) -> float:
    q = normalize(query)
    haystack = normalize(" ".join([
        item.get("material_id", ""),
        item.get("title", ""),
        item.get("type", ""),
        item.get("summary", ""),
        item.get("content", ""),
        " ".join(item.get("tags", [])),
    ]))
    score = 0.0
    if q and q in haystack:
        score += 6.0
    for token in query_tokens(query):
        if token and token in haystack:
            score += 1.0 if len(token) == 1 else 2.5
    item_tags = set(item.get("tags", []))
    for tag in tags or []:
        if tag in item_tags:
            score += 3.0
    return round(score, 4)


def search_items(actor_id: str, query: str, top_k: int = 5, types: list[str] | None = None, tags: list[str] | None = None) -> dict[str, Any]:
    items = read_items()
    types = types or []
    tags = tags or []
    candidates = []
    denied_count = 0
    type_filtered = 0
    for item in items:
        if types and item.get("type") not in types:
            type_filtered += 1
            continue
        score = score_item(item, query, tags)
        if tags and not set(tags) & set(item.get("tags", [])):
            continue
        if score <= 0 and query.strip():
            continue
        if not can_read(actor_id, item):
            denied_count += 1
            continue
        result = public_item(item)
        result["match_score"] = score
        result["kb_result_id"] = "KBR-" + uuid.uuid4().hex[:8].upper()
        candidates.append(result)
    candidates.sort(key=lambda x: (x["match_score"], x["updated_at"]), reverse=True)
    results = candidates[:top_k]
    trace = {
        "query_id": "Q-" + uuid.uuid4().hex[:10].upper(),
        "actor_id": actor_id,
        "query": query,
        "types": types,
        "tags": tags,
        "initial_candidates": len(items),
        "type_filtered_count": type_filtered,
        "permission_filtered_count": denied_count,
        "returned_count": len(results),
        "retrieval_steps": ["本地 JSON 初查", "关键词/标签 mock 重排", "按当前真人权限过滤", "返回带出处片段"],
        "mock_note": "v0.1 临时接口版未接入真实向量库，match_score 为本地关键词/标签打分。",
    }
    append_log({"time": datetime.now().isoformat(timespec="seconds"), **trace})
    return {"trace": trace, "results": results}


def get_item(actor_id: str, material_id: str) -> dict[str, Any]:
    for item in read_items():
        if item["material_id"] == material_id:
            if not can_read(actor_id, item):
                raise PermissionError("当前真人无权读取该知识库资料。")
            return public_item(item, include_content=True)
    raise KeyError(material_id)


def get_task_materials(actor_id: str, task_type: str, query: str = "", top_k: int = 8, include_templates: bool = True) -> dict[str, Any]:
    profile = TASK_PROFILES.get(task_type)
    if not profile:
        raise KeyError(task_type)
    merged_query = " ".join([profile["query_hint"], query]).strip()
    preferred = []
    missing_or_denied = []
    for material_id in profile["preferred_ids"]:
        item = next((x for x in read_items() if x["material_id"] == material_id), None)
        if not item:
            missing_or_denied.append({"material_id": material_id, "reason": "资料不存在"})
            continue
        if not include_templates and item.get("type") == "template":
            continue
        if not can_read(actor_id, item):
            missing_or_denied.append({"material_id": material_id, "reason": "当前真人无读取权限"})
            continue
        selected = public_item(item, include_content=True)
        selected["match_score"] = score_item(item, merged_query)
        selected["kb_result_id"] = "KBR-" + uuid.uuid4().hex[:8].upper()
        preferred.append(selected)

    used_ids = {x["material_id"] for x in preferred}
    supplemental_types = profile["required_types"]
    search_result = search_items(actor_id, merged_query, top_k=top_k, types=supplemental_types)
    supplemental = [x for x in search_result["results"] if x["material_id"] not in used_ids]
    materials = (preferred + supplemental)[:top_k]
    required_types = set(profile["required_types"])
    returned_types = {x["type"] for x in materials}
    readiness = "ready" if required_types <= returned_types and not missing_or_denied else "partial"
    if missing_or_denied and not materials:
        readiness = "blocked"
    package = {
        "task_material_package_id": "TMP-" + uuid.uuid4().hex[:8].upper(),
        "task_type": task_type,
        "task_name": profile["name"],
        "actor_id": actor_id,
        "readiness": readiness,
        "query": merged_query,
        "required_types": profile["required_types"],
        "returned_types": sorted(returned_types),
        "materials": materials,
        "citations": [build_citation(x) for x in materials],
        "missing_or_denied": missing_or_denied,
        "prompt_context_hint": build_prompt_context_hint(materials),
        "trace": {
            "policy": "先取任务偏好资料，再走本地检索补充；返回前按当前真人权限过滤。",
            "search_trace": search_result["trace"],
        },
    }
    append_log({
        "time": datetime.now().isoformat(timespec="seconds"),
        "query_id": package["task_material_package_id"],
        "actor_id": actor_id,
        "query": merged_query,
        "task_type": task_type,
        "returned_count": len(materials),
        "readiness": readiness,
        "missing_or_denied_count": len(missing_or_denied),
    })
    return package


def public_item(item: dict[str, Any], include_content: bool = True) -> dict[str, Any]:
    data = {
        "material_id": item["material_id"],
        "title": item["title"],
        "type": item["type"],
        "summary": item["summary"],
        "source": item["source"],
        "version": item["version"],
        "tags": item.get("tags", []),
        "permission_scope": item.get("permission_scope", []),
        "citation": item["citation"],
        "updated_at": item["updated_at"],
    }
    if include_content:
        data["content"] = item["content"]
    for optional_key in [
        "hot_case_id",
        "asset_kind",
        "file_refs",
        "decomposition",
        "style_reference",
        "reuse_constraints",
        "linked_skill_refs",
    ]:
        if optional_key in item:
            data[optional_key] = item[optional_key]
    return data


def build_citation(item: dict[str, Any]) -> dict[str, str]:
    return {
        "material_id": item["material_id"],
        "title": item["title"],
        "citation": item["citation"],
        "source": item["source"],
        "version": item["version"],
    }


def build_prompt_context_hint(materials: list[dict[str, Any]]) -> str:
    lines = []
    for item in materials:
        content = item.get("content") or item.get("summary", "")
        lines.append(f"[{item['material_id']} | {item['title']} | {item['citation']}]\n{content}")
    return "\n\n".join(lines)
