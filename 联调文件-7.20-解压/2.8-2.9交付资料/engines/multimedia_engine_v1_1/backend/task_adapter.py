from __future__ import annotations

from typing import Any


MULTIMEDIA_ENGINE_BOUNDARY = {
    "engine": "multimedia_generation",
    "owned_outputs": ["image", "video", "audio", "poster_plan", "video_edit_plan", "short_video_plan", "speech_plan", "media_processing_plan"],
    "not_owned_outputs": ["text_report", "copywriting", "article", "official_document", "cross_engine_orchestration", "human_approval_organization"],
    "principle": "多媒体生成引擎只承接流程执行引擎派发的图片、视频、音频类子任务；纯文字成果、跨引擎编排和真人确认组织不归本引擎办理。",
}


CAPABILITY_TASK_RULES: dict[str, dict[str, Any]] = {
    "text_to_image": {
        "task_type": "multimedia_poster",
        "output_type": "image_plan",
        "label": "文生图/海报方案",
        "implementation": "llm_plan",
        "required_hints": ["product_profile", "brand_style", "image_or_logo_asset", "compliance_rule"],
    },
    "text_to_video": {
        "task_type": "product_video",
        "output_type": "video_plan",
        "label": "文生视频",
        "implementation": "reserved",
        "required_hints": ["script_or_brief", "visual_reference", "brand_style"],
    },
    "video_editing": {
        "task_type": "video_editing",
        "output_type": "video_edit_plan",
        "label": "视频剪接",
        "implementation": "llm_plan",
        "required_hints": ["source_video_asset", "target_duration", "platform_or_usage"],
    },
    "fixed_short_video": {
        "task_type": "fixed_short_video",
        "output_type": "short_video_plan",
        "label": "固定类别短视频制作",
        "implementation": "llm_plan",
        "required_hints": ["text_or_script", "product_profile", "brand_style", "template_or_pattern"],
    },
    "digital_human": {
        "task_type": "product_video",
        "output_type": "digital_human_plan",
        "label": "数字人制作",
        "implementation": "reserved",
        "required_hints": ["avatar_ref", "script", "voice_or_lip_sync_requirement"],
    },
    "text_to_speech": {
        "task_type": "text_to_speech",
        "output_type": "speech_plan",
        "label": "文字转语音",
        "implementation": "llm_plan",
        "required_hints": ["script_text", "voice_requirement", "usage_scene"],
    },
    "media_processing": {
        "task_type": "media_processing",
        "output_type": "media_processing_plan",
        "label": "音画合成与媒体处理",
        "implementation": "llm_plan",
        "required_hints": ["source_media_asset", "processing_goal", "output_format"],
    },
    "music_sound": {
        "task_type": "media_processing",
        "output_type": "music_sound_plan",
        "label": "音乐音效生成",
        "implementation": "reserved",
        "required_hints": ["scene", "duration", "style"],
    },
    "multilingual_version": {
        "task_type": "media_processing",
        "output_type": "multilingual_plan",
        "label": "多语种翻译版本",
        "implementation": "reserved",
        "required_hints": ["source_media_asset", "target_languages", "subtitle_or_dubbing"],
    },
}


TASK_TYPE_TO_CAPABILITY = {
    "multimedia_poster": "text_to_image",
    "product_video": "text_to_video",
    "video_editing": "video_editing",
    "fixed_short_video": "fixed_short_video",
    "text_to_speech": "text_to_speech",
    "media_processing": "media_processing",
    "hot_case_reuse": "text_to_image",
}


def adapt_multimedia_subtask(req: Any) -> dict[str, Any]:
    input_payload = getattr(req, "input", None) or {}
    capability_payload = getattr(req, "capability", None) or {}
    requirement = _extract_requirement(req)
    requested_capability_id = (
        getattr(req, "capability_id", None)
        or capability_payload.get("capability_id")
        or input_payload.get("capability_id")
    )
    requested_task_type = getattr(req, "task_type", None) or input_payload.get("task_type")
    requested_output_type = getattr(req, "output_type", None) or input_payload.get("output_type") or (getattr(req, "expected_return", None) or {}).get("output_type")

    boundary = _boundary_check(requirement, requested_capability_id, requested_task_type)
    if not boundary["accepted"]:
        return {
            "accepted": False,
            "code": "MM_011_OUT_OF_BOUNDARY",
            "message": boundary["message"],
            "engine_boundary": MULTIMEDIA_ENGINE_BOUNDARY,
            "requested_capability_id": requested_capability_id,
            "requested_task_type": requested_task_type,
            "requirement": requirement,
            "missing_fields": [],
            "normalized": {},
        }

    capability_id = _normalize_capability_id(requested_capability_id, requested_task_type, requirement)
    rule = CAPABILITY_TASK_RULES.get(capability_id)
    if not rule:
        return {
            "accepted": False,
            "code": "MM_002_UNSUPPORTED_CAPABILITY",
            "message": "无法在多媒体生成能力清单中识别该任务，请流程执行引擎补齐 capability_id。",
            "engine_boundary": MULTIMEDIA_ENGINE_BOUNDARY,
            "requested_capability_id": requested_capability_id,
            "requested_task_type": requested_task_type,
            "requirement": requirement,
            "missing_fields": [{"field": "capability_id", "reason": "缺少明确的多媒体能力接口位。"}],
            "normalized": {},
        }
    task_type = _normalize_task_type(requested_task_type, capability_id, rule)
    output_type = requested_output_type or rule["output_type"]
    missing_fields = _missing_hints(rule, req, requirement)
    return {
        "accepted": True,
        "code": "MM_ADAPT_READY" if not missing_fields else "MM_ADAPT_PARTIAL",
        "message": "任务已在多媒体边界内完成归一化。" if not missing_fields else "任务可承办，但建议由流程执行补齐部分素材或参数。",
        "engine_boundary": MULTIMEDIA_ENGINE_BOUNDARY,
        "requested_capability_id": requested_capability_id,
        "requested_task_type": requested_task_type,
        "requested_output_type": requested_output_type,
        "requirement": requirement,
        "normalized": {
            "capability_id": capability_id,
            "task_type": task_type,
            "output_type": output_type,
            "label": rule["label"],
            "implementation": rule["implementation"],
        },
        "missing_fields": missing_fields,
        "material_requirements": rule["required_hints"],
        "handoff_note": "本适配只发生在多媒体生成引擎内部，不代表本引擎会判断跨引擎流程；最终派发仍应由流程执行引擎固化。",
    }


def _extract_requirement(req: Any) -> str:
    input_payload = getattr(req, "input", None) or {}
    return (
        getattr(req, "requirement", None)
        or input_payload.get("requirement")
        or input_payload.get("brief")
        or input_payload.get("text")
        or input_payload.get("original_text")
        or input_payload.get("task_description")
        or ""
    ).strip()


def _normalize_capability_id(capability_id: str | None, task_type: str | None, requirement: str) -> str | None:
    if capability_id in CAPABILITY_TASK_RULES:
        return capability_id
    if task_type in TASK_TYPE_TO_CAPABILITY:
        return TASK_TYPE_TO_CAPABILITY[task_type]
    text = requirement.lower()
    if any(word in text for word in ["剪辑", "剪接", "混剪", "长转短", "转成短片", "剪成"]):
        return "video_editing"
    if any(word in text for word in ["短视频", "成片", "商品视频", "课件转视频"]):
        return "fixed_short_video"
    if any(word in text for word in ["配音", "语音", "朗读", "口播音频", "文字转语音"]):
        return "text_to_speech"
    if any(word in text for word in ["字幕", "抠像", "音画合成", "格式转换", "降噪", "音频清理"]):
        return "media_processing"
    if any(word in text for word in ["数字人", "真人分身", "口型"]):
        return "digital_human"
    if any(word in text for word in ["文生视频", "生成视频"]):
        return "text_to_video"
    if any(word in text for word in ["海报", "图片", "配图", "封面", "文生图", "商品图", "版式设计"]):
        return "text_to_image"
    return None


def _normalize_task_type(task_type: str | None, capability_id: str, rule: dict[str, Any]) -> str:
    if task_type == "hot_case_reuse":
        return "hot_case_reuse"
    if task_type in TASK_TYPE_TO_CAPABILITY and TASK_TYPE_TO_CAPABILITY[task_type] == capability_id:
        return task_type
    return rule["task_type"]


def _boundary_check(requirement: str, capability_id: str | None, task_type: str | None) -> dict[str, Any]:
    if capability_id and capability_id.startswith("content_"):
        return {"accepted": False, "message": f"能力接口位 {capability_id} 属于内容产出，不归多媒体生成引擎。"}
    text = requirement.lower()
    text_words = ["文章", "报告", "公文", "通知", "纪要", "文案", "方案", "话术", "初稿", "总结"]
    media_words = ["图片", "海报", "视频", "音频", "配音", "剪辑", "剪接", "字幕", "封面", "图", "成片", "抠像"]
    if any(word in text for word in text_words) and not any(word in text for word in media_words) and not capability_id and not task_type:
        return {"accepted": False, "message": "任务描述更像纯文字成果，应由内容产出引擎承办。"}
    return {"accepted": True, "message": ""}


def _missing_hints(rule: dict[str, Any], req: Any, requirement: str) -> list[dict[str, str]]:
    input_payload = getattr(req, "input", None) or {}
    artifact_refs = set(getattr(req, "artifact_refs", []) or [])
    artifact_refs.update(input_payload.get("artifact_refs") or [])
    missing: list[dict[str, str]] = []
    if not requirement:
        missing.append({"field": "requirement", "reason": "缺少任务描述。"})
    hints = set(rule["required_hints"])
    if "source_video_asset" in hints and not artifact_refs and "视频素材" not in requirement:
        missing.append({"field": "artifact_refs", "reason": "视频剪接建议传入原始视频 artifact_refs 或明确素材来源。"})
    if "source_media_asset" in hints and not artifact_refs:
        missing.append({"field": "artifact_refs", "reason": "媒体处理建议传入源媒体 artifact_refs。"})
    if "target_duration" in hints and not any(word in requirement for word in ["秒", "分钟", "时长", "长转短"]):
        missing.append({"field": "target_duration", "reason": "建议补齐目标时长，例如 15 秒、30 秒或 1 分钟。"})
    if "voice_requirement" in hints and not any(word in requirement for word in ["男声", "女声", "音色", "真人", "配音"]):
        missing.append({"field": "voice_requirement", "reason": "文字转语音建议补齐音色、语速和使用场景。"})
    if "image_or_logo_asset" in hints and not artifact_refs and "logo" not in requirement.lower():
        missing.append({"field": "image_or_logo_asset", "reason": "图片/海报任务建议传入 Logo、产品图或风格参考。"})
    return missing

