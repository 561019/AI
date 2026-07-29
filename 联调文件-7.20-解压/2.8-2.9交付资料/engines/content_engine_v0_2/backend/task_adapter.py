from __future__ import annotations

from typing import Any


CONTENT_ENGINE_BOUNDARY = {
    "engine": "content_production",
    "owned_outputs": ["report", "copywriting", "article", "plan", "official_document", "script", "speech", "meeting_summary"],
    "not_owned_outputs": ["image", "video", "audio", "visual_layout", "real_media_file", "cross_engine_orchestration", "human_approval_organization"],
    "principle": "内容产出只承接流程执行引擎派发的文字类子任务；图片、视频、音频、跨引擎编排和真人确认组织均不归本引擎办理。",
}


CAPABILITY_RULES: dict[str, dict[str, Any]] = {
    "content_marketing_copy": {
        "content_type": "marketing_bundle",
        "template_id": "TPL-MARKETING-BUNDLE",
        "scenario_id": "REQ-115",
        "label": "营销文案组合",
        "required_hints": ["product_profile", "brand_style"],
    },
    "content_hot_case_reuse": {
        "content_type": "marketing_bundle",
        "template_id": "TPL-MARKETING-BUNDLE",
        "scenario_id": "REQ-115",
        "label": "爆款案例复用文案",
        "required_hints": ["hot_case_refs", "brand_style", "product_profile"],
    },
    "content_agronomy_fertilization_plan": {
        "content_type": "expert_plan",
        "template_id": "TPL-EXPERT-PLAN",
        "scenario_id": "REQ-EXPERT-PLAN",
        "label": "专家施肥方案",
        "required_hints": ["expert_agent_ref", "skill_refs", "rule_calculation"],
    },
    "content_report_draft": {
        "content_type": "report_draft",
        "template_id": "TPL-GENERIC-REPORT",
        "scenario_id": "REQ-GENERIC-REPORT",
        "label": "报告初稿",
        "required_hints": ["facts_or_analysis", "report_purpose"],
    },
    "content_article_draft": {
        "content_type": "article_draft",
        "template_id": "TPL-GENERIC-ARTICLE",
        "scenario_id": "REQ-GENERIC-ARTICLE",
        "label": "文章/公众号初稿",
        "required_hints": ["topic", "audience", "style"],
    },
    "content_meeting_summary": {
        "content_type": "meeting_summary",
        "template_id": "TPL-GENERIC-MEETING",
        "scenario_id": "REQ-GENERIC-MEETING",
        "label": "会议纪要/汇报稿",
        "required_hints": ["meeting_record", "participants_or_topic"],
    },
    "content_script_draft": {
        "content_type": "script_draft",
        "template_id": "TPL-GENERIC-SCRIPT",
        "scenario_id": "REQ-GENERIC-SCRIPT",
        "label": "话术/脚本初稿",
        "required_hints": ["scenario", "audience", "tone"],
    },
    "content_notice_document": {
        "content_type": "rectification_notice",
        "template_id": "TPL-RECTIFICATION-NOTICE",
        "scenario_id": "REQ-054",
        "label": "通知/公文草稿",
        "required_hints": ["facts", "basis", "deadline_or_request"],
    },
    "content_legal_draft": {
        "content_type": "legal_pleading",
        "template_id": "TPL-LEGAL-PLEADING",
        "scenario_id": "LEGAL-001",
        "label": "法律文书草稿",
        "required_hints": ["case_fact", "legal_structure"],
    },
    "content_generic_draft": {
        "content_type": "generic_text_draft",
        "template_id": "TPL-GENERIC-DRAFT",
        "scenario_id": "REQ-GENERIC-DRAFT",
        "label": "通用文字初稿",
        "required_hints": ["topic", "purpose", "audience"],
    },
}


CONTENT_TYPE_TO_CAPABILITY = {
    "marketing_bundle": "content_marketing_copy",
    "expert_plan": "content_agronomy_fertilization_plan",
    "report_draft": "content_report_draft",
    "article_draft": "content_article_draft",
    "meeting_summary": "content_meeting_summary",
    "script_draft": "content_script_draft",
    "rectification_notice": "content_notice_document",
    "legal_pleading": "content_legal_draft",
    "generic_text_draft": "content_generic_draft",
}


def adapt_content_subtask(req: Any) -> dict[str, Any]:
    input_payload = getattr(req, "input", None) or {}
    capability_payload = getattr(req, "capability", None) or {}
    requirement = _extract_requirement(req)
    requested_capability_id = (
        getattr(req, "capability_id", None)
        or capability_payload.get("capability_id")
        or input_payload.get("capability_id")
    )
    requested_content_type = getattr(req, "content_type", None) or input_payload.get("content_type")
    requested_template_id = getattr(req, "template_id", None) or input_payload.get("template_id")

    boundary = _boundary_check(requirement, requested_capability_id, requested_content_type)
    if not boundary["accepted"]:
        return {
            "accepted": False,
            "code": "CP_011_OUT_OF_BOUNDARY",
            "message": boundary["message"],
            "engine_boundary": CONTENT_ENGINE_BOUNDARY,
            "requested_capability_id": requested_capability_id,
            "requested_content_type": requested_content_type,
            "requirement": requirement,
            "missing_fields": [],
            "normalized": {},
        }

    capability_id = _normalize_capability_id(requested_capability_id, requested_content_type, requirement)
    rule = CAPABILITY_RULES.get(capability_id, CAPABILITY_RULES["content_generic_draft"])
    template_id = requested_template_id or rule["template_id"]
    content_type = requested_content_type or rule["content_type"]
    scenario_id = getattr(req, "scenario_id", None) or input_payload.get("scenario_id") or rule["scenario_id"]
    missing_fields = _missing_hints(rule, req, requirement)
    return {
        "accepted": True,
        "code": "CP_ADAPT_READY" if not missing_fields else "CP_ADAPT_PARTIAL",
        "message": "任务已在内容产出边界内完成归一化。" if not missing_fields else "任务可承办，但建议由流程执行补齐部分上下文。",
        "engine_boundary": CONTENT_ENGINE_BOUNDARY,
        "requested_capability_id": requested_capability_id,
        "requested_content_type": requested_content_type,
        "requested_template_id": requested_template_id,
        "requirement": requirement,
        "normalized": {
            "capability_id": capability_id,
            "content_type": content_type,
            "template_id": template_id,
            "scenario_id": scenario_id,
            "label": rule["label"],
        },
        "missing_fields": missing_fields,
        "material_requirements": rule["required_hints"],
        "handoff_note": "本适配只发生在内容产出引擎内部，不代表本引擎会判断跨引擎流程；最终派发仍应由流程执行引擎固化。",
    }


def _extract_requirement(req: Any) -> str:
    input_payload = getattr(req, "input", None) or {}
    return (
        getattr(req, "input_brief", None)
        or input_payload.get("requirement")
        or input_payload.get("input_brief")
        or input_payload.get("brief")
        or input_payload.get("text")
        or input_payload.get("original_text")
        or input_payload.get("task_description")
        or ""
    ).strip()


def _normalize_capability_id(requested_capability_id: str | None, content_type: str | None, requirement: str) -> str:
    if requested_capability_id in CAPABILITY_RULES:
        return requested_capability_id
    if requested_capability_id and requested_capability_id.startswith("content_"):
        return "content_generic_draft"
    if content_type in CONTENT_TYPE_TO_CAPABILITY:
        return CONTENT_TYPE_TO_CAPABILITY[content_type]
    text = requirement.lower()
    if any(word in text for word in ["爆款", "复用", "爆文"]):
        return "content_hot_case_reuse"
    if any(word in text for word in ["施肥", "甘蔗", "专家分身", "农艺"]):
        return "content_agronomy_fertilization_plan"
    if any(word in text for word in ["起诉", "答辩", "合同纠纷", "法律文书", "律师"]):
        return "content_legal_draft"
    if any(word in text for word in ["整改通知", "通知书", "公文", "通报", "函"]):
        return "content_notice_document"
    if any(word in text for word in ["会议纪要", "会议总结", "汇报稿", "纪要"]):
        return "content_meeting_summary"
    if any(word in text for word in ["公众号", "推文", "文章", "新闻稿", "科普"]):
        return "content_article_draft"
    if any(word in text for word in ["报告", "分析报告", "总结报告", "研发方案", "方案"]):
        return "content_report_draft"
    if any(word in text for word in ["话术", "脚本", "口播", "主持词", "销售话术"]):
        return "content_script_draft"
    if any(word in text for word in ["文案", "营销", "宣传", "卖点"]):
        return "content_marketing_copy"
    return "content_generic_draft"


def _boundary_check(requirement: str, capability_id: str | None, content_type: str | None) -> dict[str, Any]:
    if capability_id and not capability_id.startswith("content_"):
        return {"accepted": False, "message": f"能力接口位 {capability_id} 不属于内容产出引擎。"}
    if content_type in {"image", "video", "audio", "poster_plan", "video_plan", "speech_plan"}:
        return {"accepted": False, "message": f"content_type={content_type} 属于多媒体成果，不归内容产出引擎承办。"}
    text = requirement.lower()
    media_words = ["图片", "海报", "视频", "音频", "配音", "剪辑", "剪接", "生成图片", "生成视频", "文生图", "文生视频"]
    text_words = ["文案", "文章", "报告", "方案", "公文", "通知", "话术", "脚本", "纪要", "说明", "总结", "初稿"]
    if any(word in text for word in media_words) and not any(word in text for word in text_words):
        return {"accepted": False, "message": "任务描述更像图片/视频/音频成果，应由多媒体生成引擎承办。"}
    return {"accepted": True, "message": ""}


def _missing_hints(rule: dict[str, Any], req: Any, requirement: str) -> list[dict[str, str]]:
    input_payload = getattr(req, "input", None) or {}
    refs = set(getattr(req, "source_material_refs", []) or [])
    refs.update(input_payload.get("source_material_refs") or [])
    refs.update(input_payload.get("artifact_refs") or [])
    missing: list[dict[str, str]] = []
    if not requirement:
        missing.append({"field": "requirement", "reason": "缺少任务描述。"})
    if "hot_case_refs" in rule["required_hints"] and not input_payload.get("hot_case_refs") and not refs:
        missing.append({"field": "hot_case_refs", "reason": "爆款复用建议传入 hot_case_refs 或已审核爆款样板引用。"})
    if "expert_agent_ref" in rule["required_hints"] and not input_payload.get("expert_agent_ref"):
        missing.append({"field": "expert_agent_ref", "reason": "专家方案应传入数字资产引擎解析后的专家分身引用。"})
    if "skill_refs" in rule["required_hints"] and not input_payload.get("skill_refs"):
        missing.append({"field": "skill_refs", "reason": "专家方案/爆款复用建议传入已登记技能引用。"})
    if "meeting_record" in rule["required_hints"] and not refs and len(requirement) < 80:
        missing.append({"field": "meeting_record", "reason": "会议纪要建议传入会议记录或较完整的会议摘要。"})
    return missing

