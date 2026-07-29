from __future__ import annotations

from datetime import datetime
from typing import Any, Callable
import uuid

from .config import get_config
from .kb_client import get_task_materials, render_xml_context
from .llm_client import build_messages, call_llm


ProgressWriter = Callable[[dict[str, Any]], None]

CAPABILITY_INTERFACES: dict[str, dict[str, str]] = {
    "text_to_image": {
        "name": "文生图",
        "batch": "首批",
        "scope": "含图生图、图片编辑、商品图、版式设计图",
        "implementation": "llm_plan",
        "default_output_type": "image_plan",
    },
    "text_to_video": {
        "name": "文生视频",
        "batch": "预留",
        "scope": "含图生视频",
        "implementation": "reserved",
        "default_output_type": "video_plan",
    },
    "video_editing": {
        "name": "视频剪接",
        "batch": "首批",
        "scope": "拆分、筛选、拼接、混剪、长转短",
        "implementation": "llm_plan",
        "default_output_type": "video_edit_plan",
    },
    "fixed_short_video": {
        "name": "固定类别短视频制作",
        "batch": "首批",
        "scope": "文字成片、商品成片、课件转视频等固定套路组装",
        "implementation": "llm_plan",
        "default_output_type": "short_video_plan",
    },
    "digital_human": {
        "name": "数字人制作",
        "batch": "预留",
        "scope": "形象与口型驱动、真人分身",
        "implementation": "reserved",
        "default_output_type": "digital_human_plan",
    },
    "text_to_speech": {
        "name": "文字转语音",
        "batch": "首批",
        "scope": "预设音色 + 指定真人音色",
        "implementation": "llm_plan",
        "default_output_type": "speech_plan",
    },
    "media_processing": {
        "name": "音画合成与媒体处理",
        "batch": "首批",
        "scope": "合成成片、字幕、抠像、音频清理、格式转换",
        "implementation": "llm_plan",
        "default_output_type": "media_processing_plan",
    },
    "music_sound": {
        "name": "音乐音效生成",
        "batch": "预留",
        "scope": "按描述生成背景音乐与音效",
        "implementation": "reserved",
        "default_output_type": "music_sound_plan",
    },
    "multilingual_version": {
        "name": "多语种翻译版本",
        "batch": "预留",
        "scope": "多语种配音与字幕版本",
        "implementation": "reserved",
        "default_output_type": "multilingual_plan",
    },
}


def run_integration(req: Any, progress_writer: ProgressWriter | None = None) -> dict[str, Any]:
    cfg = get_config()
    capability = CAPABILITY_INTERFACES.get(req.capability_id)
    task_id = getattr(req, "task_id", None) or "MM-KB-" + uuid.uuid4().hex[:8].upper()
    started_at = datetime.now().isoformat(timespec="seconds")
    events = [
        {"time": started_at, "step": "receive_subtask", "status": "ok", "detail": "已接收流程派发的多媒体子任务。"},
    ]
    material_package = None
    rendered = {"xml_context": "", "references": []}
    messages = []
    llm_result = None
    status = "received"
    error = None
    _emit(
        progress_writer,
        _build_result(task_id, started_at, status, req, cfg, material_package, rendered, messages, llm_result, events, error),
    )
    status = "running"
    try:
        events.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "step": "validate_subtask",
                "status": "ok",
                "detail": "子任务字段已通过接口模型校验，包含真人、任务类型、能力接口位、产出类型和需求描述。",
            }
        )
        task_adaptation = getattr(req, "task_adaptation", {}) or {}
        if task_adaptation:
            normalized = task_adaptation.get("normalized") or {}
            events.append(
                {
                    "time": datetime.now().isoformat(timespec="seconds"),
                    "step": "task_adaptation",
                    "status": "ok" if task_adaptation.get("accepted") else "failed",
                    "detail": f"任务适配：{task_adaptation.get('message')} capability={normalized.get('capability_id')} task_type={normalized.get('task_type')}",
                    "data": {"missing_fields": task_adaptation.get("missing_fields", [])},
                }
            )
        events.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "step": "capability_route",
                "status": "failed" if capability is None else "ok",
                "detail": capability_route_detail(req.capability_id, capability),
            }
        )
        if capability is None:
            status = "unable_to_handle"
            error = f"未知能力接口位：{req.capability_id}"
            events.append(
                {
                    "time": datetime.now().isoformat(timespec="seconds"),
                    "step": "exit_decision",
                    "status": "failed",
                    "detail": "三种出口判定：无法办理。原因：能力接口位未登记。",
                }
            )
            result = _build_result(task_id, started_at, status, req, cfg, material_package, rendered, messages, llm_result, events, error)
            _emit(progress_writer, result)
            return result
        if capability.get("implementation") == "reserved":
            status = "unable_to_handle"
            error = f"{capability['name']}接口位已登记为预留，当前版本尚未挂接实现方案。"
            llm_result = reserved_capability_result(req, capability, error)
            events.append(
                {
                    "time": datetime.now().isoformat(timespec="seconds"),
                    "step": "exit_decision",
                    "status": "failed",
                    "detail": "三种出口判定：无法办理。原因：该能力接口位为预留。",
                }
            )
            events.append(
                {
                    "time": datetime.now().isoformat(timespec="seconds"),
                    "step": "return_result",
                    "status": "failed",
                    "detail": "已返回预留接口位说明，等待后续挂接具体实现方案。",
                }
            )
            result = _build_result(task_id, started_at, status, req, cfg, material_package, rendered, messages, llm_result, events, error)
            _emit(progress_writer, result)
            return result
        _emit(
            progress_writer,
            _build_result(task_id, started_at, status, req, cfg, material_package, rendered, messages, llm_result, events, error),
        )
        material_package = get_task_materials(cfg["KB_BASE"], req.actor_id, req.task_type, req.requirement, req.top_k)
        events.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "step": "kb_task_materials",
                "status": "ok",
                "detail": f"知识库返回 {len(material_package.get('materials', []))} 条可用资料，readiness={material_package.get('readiness')}",
            }
        )
        _emit(
            progress_writer,
            _build_result(task_id, started_at, status, req, cfg, material_package, rendered, messages, llm_result, events, error),
        )
        rendered = render_xml_context(material_package)
        events.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "step": "render_xml_context",
                "status": "ok",
                "detail": f"已渲染 {len(rendered['references'])} 个 context。",
            }
        )
        messages = build_messages(req.requirement, rendered["xml_context"], req.capability_id, req.output_type)
        _emit(
            progress_writer,
            _build_result(task_id, started_at, status, req, cfg, material_package, rendered, messages, llm_result, events, error),
        )
    except Exception as exc:
        status = "failed"
        error = str(exc)
        events.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "step": "error",
                "status": "failed",
                "detail": error,
            }
        )
        events.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "step": "exit_decision",
                "status": "failed",
                "detail": "素材、字段或知识库环节失败，按三种出口判定为：无法办理。",
            }
        )
        events.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "step": "return_result",
                "status": "failed",
                "detail": "已把无法办理原因返回流程执行引擎/调用方。",
            }
        )
        result = _build_result(task_id, started_at, status, req, cfg, material_package, rendered, messages, llm_result, events, error)
        _emit(progress_writer, result)
        return result

    try:
        events.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "step": "llm_call",
                "status": "running",
                "detail": "开始调用文本大模型生成多媒体制作方案/提示词。",
            }
        )
        _emit(
            progress_writer,
            _build_result(task_id, started_at, status, req, cfg, material_package, rendered, messages, llm_result, events, error),
        )
        llm_result = call_llm(cfg, messages, req.use_llm)
        events.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "step": "llm_call",
                "status": "ok",
                "detail": f"LLM 调用完成，mode={llm_result.get('mode')}",
            }
        )
        status = "completed"
        exit_type = decide_exit_type(status, req, llm_result)
        events.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "step": "assemble_check_label",
                "status": "ok",
                "detail": "已完成方案字段、素材引用和合规提示核查；当前联调版尚未生成真实媒体文件，显式/隐式标识待图片/视频生成接口接入后执行。",
            }
        )
        events.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "step": "exit_decision",
                "status": "ok",
                "detail": f"三种出口判定：{exit_label(exit_type)}。",
            }
        )
        events.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "step": "return_result",
                "status": "ok",
                "detail": return_detail(exit_type),
            }
        )
    except Exception as exc:
        status = "llm_failed"
        error = str(exc)
        llm_result = {
            "mode": "error",
            "error": error,
            "note": "知识库取材、XML 渲染和 messages 组装已经完成，失败点只在真实 LLM 接口调用。",
        }
        events.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "step": "llm_call",
                "status": "failed",
                "detail": error,
            }
        )
        events.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "step": "exit_decision",
                "status": "failed",
                "detail": "模型调度/文本 LLM 调用失败，按三种出口判定为：无法办理。",
            }
        )
        events.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "step": "return_result",
                "status": "failed",
                "detail": "已把 LLM 失败原因返回流程执行引擎/调用方。",
            }
        )
    result = _build_result(task_id, started_at, status, req, cfg, material_package, rendered, messages, llm_result, events, error)
    _emit(progress_writer, result)
    return result


def _build_result(
    task_id: str,
    started_at: str,
    status: str,
    req: Any,
    cfg: dict[str, str],
    material_package: dict[str, Any] | None,
    rendered: dict[str, Any],
    messages: list[dict[str, str]],
    llm_result: dict[str, Any] | None,
    events: list[dict[str, str]],
    error: str | None,
) -> dict[str, Any]:
    artifact_refs = []
    hot_case_reuse = _build_hot_case_reuse_info(material_package, req)
    digital_asset_skill_usage = _build_digital_asset_skill_usage(req)
    model_dispatch_usage = _build_model_dispatch_usage(req, llm_result)
    media_outputs = {
        "media_type": media_type_for_output(req.output_type),
        "artifact_refs": artifact_refs,
        "preview_url": None,
        "file_ref": None,
        "reuse_mode": "hot_case_reuse" if hot_case_reuse.get("enabled") else None,
        "hot_case_refs": hot_case_reuse.get("hot_case_refs", []),
        "label_status": "pending_real_media_generation",
        "ai_generation_label": {
            "required": True,
            "status": "pending_real_media_generation",
            "type": "explicit_or_implicit_after_real_media_generation",
        },
        "note": "本地联调版仅生成方案/提示词；真实媒体文件接入后在此返回 artifact_refs、preview_url 或 file_ref。",
    }
    permission_result = {
        "mode": "local_mock",
        "decision_id": getattr(req, "decision_id", None) or f"DECISION-{task_id}",
        "allowed": status not in {"failed", "unable_to_handle"},
        "audit_ref": getattr(req, "audit_ref", None) or f"AUDIT-{task_id}",
    }
    return {
        "task_id": task_id,
        "created_at": started_at,
        "status": status,
        "message_id": getattr(req, "message_id", None),
        "parent_message_id": getattr(req, "parent_message_id", None),
        "workflow_instance_id": getattr(req, "workflow_instance_id", None) or getattr(req, "parent_flow_id", None),
        "node_id": getattr(req, "node_id", None),
        "upstream_task_id": getattr(req, "task_id", None),
        "idempotency_key": getattr(req, "idempotency_key", None),
        "actor_id": req.actor_id,
        "task_type": req.task_type,
        "capability_id": req.capability_id,
        "output_type": req.output_type,
        "capability_profile": CAPABILITY_INTERFACES.get(req.capability_id),
        "task_adaptation": getattr(req, "task_adaptation", {}) or {},
        "requirement": req.requirement,
        "source_engine": getattr(req, "source_engine", None),
        "source_engine_name": getattr(req, "source_engine_name", None),
        "parent_flow_id": getattr(req, "parent_flow_id", None),
        "trace_id": getattr(req, "trace_id", None),
        "upstream_content_task_id": getattr(req, "upstream_content_task_id", None),
        "upstream_content_summary": getattr(req, "upstream_content_summary", None),
        "content_artifact_ref": getattr(req, "content_artifact_ref", None),
        "input_artifact_refs": getattr(req, "artifact_refs", []),
        "kb_base": cfg["KB_BASE"],
        "material_package": material_package,
        "xml_context": rendered["xml_context"],
        "references": rendered["references"],
        "messages": messages,
        "llm_result": llm_result,
        "model_dispatch_usage": model_dispatch_usage,
        "artifact_refs": artifact_refs,
        "media_outputs": media_outputs,
        "hot_case_reuse": hot_case_reuse,
        "digital_asset_skill_usage": digital_asset_skill_usage,
        "permission_result": permission_result,
        "security_check_status": "local_mock_passed" if status not in {"failed", "unable_to_handle"} else "local_mock_not_passed",
        "audit_ref": permission_result["audit_ref"],
        "exit_type": decide_exit_type(status, req, llm_result),
        "events": events,
        "error": error,
        "truth_note": "v1.1 真实调用本地知识库接口，并在多媒体边界内做任务归一和缺项提示；LLM 是否真实调用取决于配置和 use_llm。没有真实图片/视频生成。",
    }


def _build_hot_case_reuse_info(material_package: dict[str, Any] | None, req: Any) -> dict[str, Any]:
    input_payload = getattr(req, "input", {}) or {}
    hot_case_materials = [
        {
            "material_id": item.get("material_id"),
            "title": item.get("title"),
            "citation": item.get("citation"),
            "source": item.get("source"),
        }
        for item in (material_package or {}).get("materials", [])
        if item.get("type") in {"hot_case", "hot_case_original", "hot_case_breakdown"}
    ]
    explicit_hot_case = (
        getattr(req, "task_type", "") == "hot_case_reuse"
        or bool(input_payload.get("reuse_mode"))
        or bool(input_payload.get("hot_case_refs"))
        or input_payload.get("batch_index") is not None
    )
    hot_case_refs = input_payload.get("hot_case_refs") or ([item.get("material_id") for item in hot_case_materials if item.get("material_id")] if explicit_hot_case else [])
    return {
        "enabled": explicit_hot_case,
        "reuse_mode": input_payload.get("reuse_mode") or ("hot_case_reuse" if explicit_hot_case else None),
        "batch_index": input_payload.get("batch_index"),
        "batch_count": input_payload.get("batch_count"),
        "hot_case_refs": hot_case_refs,
        "hot_case_materials": hot_case_materials,
        "boundary_note": "爆款复用在本版本只承办取材、画面方案和提示词生成；真实图片/视频生成和爆款效果验证待后续接口接入。",
    }


def _build_digital_asset_skill_usage(req: Any) -> dict[str, Any]:
    input_payload = getattr(req, "input", {}) or {}
    skill_refs = getattr(req, "skill_refs", None) or input_payload.get("skill_refs") or []
    skill_requirements = getattr(req, "skill_requirements", None) or input_payload.get("skill_requirements") or []
    slot = getattr(req, "digital_asset_interface_slot", None) or input_payload.get("digital_asset_interface_slot") or {}
    return {
        "enabled": bool(skill_refs or skill_requirements or slot),
        "status": "reserved_interface",
        "target_service": slot.get("target_service") or "l2.digital_asset_engine",
        "target_engine": slot.get("target_engine") or "数字资产引擎",
        "expected_action": slot.get("required_action") or "skills.resolve",
        "expected_path": slot.get("expected_path") or "POST /api/digital-assets/skills/resolve",
        "skill_refs": skill_refs,
        "skill_requirements": skill_requirements,
        "truth_note": "本地没有实现数字资产引擎，当前仅保留爆款模式与制作标准技能的取用接口位；多媒体不创建、不修改技能。",
    }


def _build_model_dispatch_usage(req: Any, llm_result: dict[str, Any] | None) -> dict[str, Any]:
    input_payload = getattr(req, "input", {}) or {}
    slot = getattr(req, "model_dispatch_interface_slot", None) or input_payload.get("model_dispatch_interface_slot") or {}
    mode = (llm_result or {}).get("mode")
    return {
        "enabled": bool(getattr(req, "use_llm", False) or slot),
        "status": "reserved_interface",
        "target_service": slot.get("target_service") or "l1.model_dispatch",
        "target_module": slot.get("target_module") or "1.5 大模型调度",
        "expected_action": slot.get("required_action") or "model.chat_completion",
        "expected_path": slot.get("expected_path") or "POST /api/model-dispatch/chat-completions",
        "request_schema_version": slot.get("request_schema_version") or "to_be_confirmed",
        "response_schema_version": slot.get("response_schema_version") or "to_be_confirmed",
        "timeout_seconds": slot.get("timeout_seconds") or slot.get("timeout") or None,
        "local_fallback_mode": mode or ("mock_prompt_only" if not getattr(req, "use_llm", False) else "pending_llm_result"),
        "truth_note": "正式架构中，多媒体凡涉及模型应调用 1.5 大模型调度；本地版暂用 LiteLLM/Kimi 直连或 mock 方案验证联调。",
    }


def media_type_for_output(output_type: str) -> str:
    if "video" in output_type:
        return "video"
    if "speech" in output_type or "audio" in output_type or "music" in output_type:
        return "audio"
    if "image" in output_type or "poster" in output_type:
        return "image"
    return "multimedia_plan"


def _emit(progress_writer: ProgressWriter | None, result: dict[str, Any]) -> None:
    if progress_writer is not None:
        progress_writer(result)


def decide_exit_type(status: str, req: Any, llm_result: dict[str, Any] | None) -> str | None:
    if status in {"failed", "llm_failed", "unable_to_handle"}:
        return "unable_to_handle"
    if status != "completed":
        return None
    parsed = (llm_result or {}).get("parsed_json")
    if isinstance(parsed, dict) and parsed.get("human_review_required") is True:
        return "pending_human_confirmation"
    if getattr(req, "capability_id", "") in {"digital_human", "text_to_speech"}:
        return "pending_human_confirmation"
    return "direct_delivery"


def exit_label(exit_type: str | None) -> str:
    labels = {
        "direct_delivery": "直接交付",
        "unable_to_handle": "无法办理",
        "pending_human_confirmation": "待真人确认",
    }
    return labels.get(exit_type or "", "待判定")


def return_detail(exit_type: str | None) -> str:
    if exit_type == "pending_human_confirmation":
        return "成果作为待确认件交回流程执行引擎，由流程执行引擎组织真人确认，本引擎不自行办理确认。"
    if exit_type == "unable_to_handle":
        return "成果无法办理，已返回原因。"
    return "成果沿原链路返回流程执行引擎，并逐级返回 L4 发起人。"


def capability_route_detail(capability_id: str, capability: dict[str, str] | None) -> str:
    if capability is None:
        return f"能力接口位 {capability_id} 未登记，不能继续承办。"
    if capability.get("implementation") == "reserved":
        return f"能力接口位识别为 {capability_id} · {capability['name']}（{capability['scope']}），批次=预留，当前只保留接口位，不调用生成实现。"
    return f"能力接口位识别为 {capability_id} · {capability['name']}（{capability['scope']}），批次=首批；当前联通取材与文本 LLM/Mock 方案生成，真实媒体文件生成按后续实现挂接。"


def reserved_capability_result(req: Any, capability: dict[str, str], reason: str) -> dict[str, Any]:
    parsed = {
        "title": f"{capability['name']}接口位预留说明",
        "capability_id": req.capability_id,
        "output_type": req.output_type or capability.get("default_output_type"),
        "production_brief": reason,
        "visual_brief": reason,
        "positive_prompt": "",
        "negative_prompt": "",
        "material_usage": [],
        "compliance_notes": ["该能力接口位已纳入统一登记，但当前版本不产出实际媒体部件。"],
        "human_review_required": False,
        "citations": [],
    }
    return {
        "mode": "reserved_interface",
        "reason": reason,
        "content": reason,
        "parsed_json": parsed,
    }
