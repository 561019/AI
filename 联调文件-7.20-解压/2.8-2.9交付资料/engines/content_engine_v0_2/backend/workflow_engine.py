from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from .audit_log import write_log
from .mock_data import (
    POSITION_TO_USER,
    SCENARIOS,
    SOURCE_MATERIALS,
    SUBTASK_REQUIRED_FIELDS,
    TEMPLATES,
    USERS,
    WORKFLOW_STEPS,
)
from .permission_engine import check_permission
from .registry import create_registry, result_id_for_task, update_registry_status

TERMINAL_STATUSES = {
    "returned_for_completion",
    "blocked_permission",
    "completed",
    "unable_to_handle",
    "rejected",
    "frozen",
}


def new_task(actor_id: str, scenario_id: str, requirement: str | None = None) -> dict[str, Any]:
    if actor_id not in USERS:
        raise ValueError("actor_id 不存在")
    if scenario_id not in SCENARIOS:
        raise ValueError("scenario_id 不存在")
    scenario = SCENARIOS[scenario_id]
    task_id = "CP-" + uuid.uuid4().hex[:8].upper()
    task = {
        "task_id": task_id,
        "trace_id": "TRACE-" + uuid.uuid4().hex[:10].upper(),
        "result_id": "CPR-" + uuid.uuid4().hex[:8].upper(),
        "actor_id": actor_id,
        "scenario_id": scenario_id,
        "requirement": requirement or scenario["l4_request"],
        "status": "created",
        "current_step_index": -1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "subtask": None,
        "subtask_validation": None,
        "permission_records": [],
        "intent_result": None,
        "content_mode": None,
        "source_package": None,
        "prompt_context": None,
        "model_dispatch": None,
        "cost_record": None,
        "drafts": [],
        "quality_report": None,
        "labels": None,
        "review_package": None,
        "approval": None,
        "registry_id": None,
        "exit_type": None,
        "review_status": "not_required",
        "blocking_reason": None,
        "error_code": None,
        "mock_notes": [
            "v0.2 任务适配版使用 mock 资料、mock 模型调度、mock 成果登记。",
            "字段校验、权限阻断、状态分流、出口判定为真实后端逻辑。",
            "任务适配只在内容产出边界内做归一化，不替代意图分析和流程执行引擎。",
        ],
    }
    write_log(task_id, actor_id, "task:create", scenario_id, "allow", "L4 请求已形成内容产出任务追踪编号。", layer="L4")
    return task


def run_all_steps(task: dict[str, Any]) -> dict[str, Any]:
    guard = 0
    while task["status"] not in TERMINAL_STATUSES and task["status"] != "pending_human_confirmation" and guard < 30:
        task = run_next_step(task)
        guard += 1
    return task


def run_next_step(task: dict[str, Any]) -> dict[str, Any]:
    if task["status"] in TERMINAL_STATUSES or task["status"] == "pending_human_confirmation":
        return task

    next_index = task["current_step_index"] + 1
    if next_index >= len(WORKFLOW_STEPS):
        task["status"] = "completed"
        return task

    task["current_step_index"] = next_index
    step = WORKFLOW_STEPS[next_index]
    scenario = SCENARIOS[task["scenario_id"]]
    task["status"] = _status_for_step(step["key"])
    write_log(task["task_id"], task["actor_id"], "workflow:step", step["key"], "allow", f"执行节点：{step['name']}", layer=step["layer"])

    if step["key"] == "l4_request":
        task["l4_request"] = {
            "request_text": task["requirement"],
            "operator_real_person_id": USERS[task["actor_id"]]["real_person_id"],
            "dialog_id": "DIALOG-CONTENT-MOCK-001",
        }
    elif step["key"] == "intent_analysis":
        task["intent_result"] = {
            "engine": "意图分析引擎",
            "intent": "content_production",
            "content_type": scenario["content_type"],
            "confidence": 0.93,
            "task_items": [
                {
                    "service": scenario["requested_service"],
                    "reason": "最终成果为文字稿件，归内容产出引擎办理。",
                }
            ],
            "not_owned_by_this_engine": ["资料检索", "数据分析", "图片/视频/音频生成", "真人审批组织"],
        }
    elif step["key"] == "process_dispatch":
        if not task.get("subtask"):
            task["subtask"] = build_subtask(task, scenario)
    elif step["key"] == "receive_subtask":
        task["subtask_validation"] = validate_subtask(task.get("subtask") or {})
        if not task["subtask_validation"]["passed"]:
            _stop(task, "returned_for_completion", "CP_001_MISSING_FIELD", "子任务六项字段不完整，退回流程执行引擎补齐。")
            return task
        record = check_permission(task["actor_id"], "TASK-CONTENT-NEW", "receive_content_subtask", task_id=task["task_id"])
        append_permission(task, record, critical=True)
    elif step["key"] == "permission_precheck":
        if task["status"] == "blocked_permission":
            return task
        template = TEMPLATES.get(scenario["template_id"])
        if not template or template["state"] != "active":
            _stop(task, "unable_to_handle", "CP_005_TEMPLATE_NOT_FOUND", "模板缺失或未启用，本引擎不能绕过模板直接生成正式文字成果。")
            return task
        for record in [
            check_permission(task["actor_id"], "TASK-CONTENT-NEW", "classify_content_type", task_id=task["task_id"]),
            check_permission(task["actor_id"], scenario["template_id"], "use_template", task_id=task["task_id"]),
        ]:
            append_permission(task, record, critical=True)
            if task["status"] == "blocked_permission":
                return task
    elif step["key"] == "classify_template":
        task["content_mode"] = build_content_mode(scenario)
    elif step["key"] == "fetch_context":
        source_package = []
        for ref in scenario["source_material_refs"]:
            source = SOURCE_MATERIALS.get(ref)
            if not source or source.get("state") != "active":
                _stop(task, "returned_for_completion", "CP_004_SOURCE_MATERIAL_MISSING", f"依据资料 {ref} 缺失或不可用，退回流程执行引擎补齐。")
                return task
            action = "retrieve_knowledge" if ref.startswith("KB-") else "read_source_material"
            record = check_permission(task["actor_id"], ref, action, task_id=task["task_id"])
            append_permission(task, record, critical=True)
            if task["status"] == "blocked_permission":
                return task
            source_package.append({"ref_id": ref, **source})
        task["source_package"] = {
            "source_materials": source_package,
            "principle": "内容依据真实输入与检索结果撰写；数字、法规、案件事实不由模型自行改写。",
        }
    elif step["key"] == "dispatch_model":
        for action in ["use_prompt", "dispatch_model"]:
            record = check_permission(task["actor_id"], "TASK-CONTENT-NEW", action, task_id=task["task_id"])
            append_permission(task, record, critical=True)
            if task["status"] == "blocked_permission":
                return task
        task["prompt_context"] = build_prompt_context(task, scenario)
        task["model_dispatch"] = build_model_dispatch(task, scenario)
        task["cost_record"] = build_cost_record(task, scenario)
        write_log(task["task_id"], task["actor_id"], "model:dispatch", task["model_dispatch"]["model_task_id"], "allow", "1.5 大模型调度 mock 完成。", layer="L1-1.5")
    elif step["key"] == "generate_draft":
        record = check_permission(task["actor_id"], "TASK-CONTENT-NEW", "generate_draft", task_id=task["task_id"])
        append_permission(task, record, critical=True)
        if task["status"] == "blocked_permission":
            return task
        task["drafts"] = build_drafts(task, scenario)
        task["semantic_summary"] = build_semantic_summary(task, scenario)
        task["semantic_keywords"] = [scenario["content_type_label"], "AI 生成待审核" if scenario["exit_policy"] != "direct_delivery" else "内部初稿", "内容产出"]
    elif step["key"] == "check_label_exit":
        for action in ["quality_check", "add_ai_label"]:
            record = check_permission(task["actor_id"], "TASK-CONTENT-NEW", action, task_id=task["task_id"])
            append_permission(task, record, critical=True)
            if task["status"] == "blocked_permission":
                return task
        task["quality_report"] = build_quality_report(task, scenario)
        task["labels"] = build_labels(task, scenario)
        task["exit_type"] = decide_exit_type(scenario)
        if task["exit_type"] == "pending_human_confirmation":
            task["review_status"] = "waiting"
            task["approval"] = build_approval(task, scenario)
            task["review_package"] = build_review_package(task, scenario)
        elif task["exit_type"] == "direct_delivery":
            task["review_status"] = "draft_delivered"
        else:
            _stop(task, "unable_to_handle", "CP_002_UNSUPPORTED_CONTENT_TYPE", "当前内容类型或模板条件不足，无法办理。")
            return task
    elif step["key"] == "register_return":
        record = check_permission(task["actor_id"], result_id_for_task(task), "register_content_result", task_id=task["task_id"])
        append_permission(task, record, critical=True)
        if task["status"] == "blocked_permission":
            return task
        registry = create_registry(task)
        task["registry_id"] = registry["registry_id"]
        deliver_record = check_permission(task["actor_id"], result_id_for_task(task), "deliver_result", task_id=task["task_id"])
        append_permission(task, deliver_record, critical=True)
        if task["status"] == "blocked_permission":
            return task
        if task["exit_type"] == "pending_human_confirmation":
            task["status"] = "pending_human_confirmation"
            task["blocking_reason"] = "已生成待审核材料包，交回流程执行引擎组织真人确认。"
            task["error_code"] = "CP_008_HUMAN_REVIEW_REQUIRED"
            write_log(task["task_id"], task["actor_id"], "workflow:return", task["task_id"], "allow", "成果作为待审核初稿返回流程执行引擎。", layer="L2")
        else:
            task["status"] = "completed"
            task["blocking_reason"] = None
            write_log(task["task_id"], task["actor_id"], "workflow:return", task["task_id"], "allow", "内部初稿直接交付给流程执行引擎。", layer="L2")

    return task


def _status_for_step(key: str) -> str:
    if key == "fetch_context":
        return "preparing_context"
    if key == "dispatch_model":
        return "dispatching_model"
    if key == "generate_draft":
        return "drafting"
    if key == "check_label_exit":
        return "checking"
    return "running"


def _stop(task: dict[str, Any], status: str, error_code: str, reason: str) -> None:
    task["status"] = status
    task["exit_type"] = "blocked" if status == "blocked_permission" else status
    task["blocking_reason"] = reason
    task["error_code"] = error_code
    write_log(task["task_id"], task["actor_id"], "workflow:stop", status, "deny", reason, layer="workflow")


def append_permission(task: dict[str, Any], record: dict[str, Any], critical: bool) -> None:
    task.setdefault("permission_records", []).append(record)
    if critical and record["result"] != "allow":
        _stop(task, "blocked_permission", "CP_003_PERMISSION_DENIED", record["reason"])


def build_subtask(task: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        "caller_engine": "流程执行引擎",
        "requested_service": scenario["requested_service"],
        "content_type": scenario["content_type"],
        "input_brief": task["requirement"],
        "expected_output": scenario["expected_output"],
        "trace_id": task["trace_id"],
        "operator_real_person_id": USERS[task["actor_id"]]["real_person_id"],
        "source_material_refs": scenario["source_material_refs"],
        "template_id": scenario["template_id"],
        "review_policy": scenario["review_policy"],
        "security_context": {
            "network_policy": "核心资料默认不出网；v0.1 仅展示 mock 调度。",
            "data_policy": "先定位资料，再按当前操作真人过权限。",
        },
    }


def validate_subtask(subtask: dict[str, Any]) -> dict[str, Any]:
    checks = []
    missing = []
    for field, label in SUBTASK_REQUIRED_FIELDS:
        value = subtask.get(field)
        passed = value not in (None, "")
        checks.append({"field": field, "label": label, "passed": passed, "value": value})
        if not passed:
            missing.append(label)
    return {
        "passed": not missing,
        "checks": checks,
        "missing_fields": missing,
        "note": "对应方案中“谁在调用、请求哪项服务、请求类型、传入内容、期望返回、追踪编号”六项标准。",
    }


def build_content_mode(scenario: dict[str, Any]) -> dict[str, Any]:
    template = TEMPLATES[scenario["template_id"]]
    return {
        "content_type": scenario["content_type"],
        "content_type_label": scenario["content_type_label"],
        "template_id": scenario["template_id"],
        "template_name": template["name"],
        "template_version": template["version"],
        "required_sections": template["required_sections"],
        "review_policy": template["review_policy"],
        "boundary_note": "本引擎只负责文字成文；资料检索、分析计算、图片视频音频生成、审批组织均不在本引擎。",
    }


def build_prompt_context(task: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        "prompt_version": f"PROMPT-CONTENT-{scenario['content_type'].upper()}-v0.1",
        "negative_prompt_version": "NEG-NO-FABRICATION-v1.0",
        "context_refs": [
            {"type": "dialog", "id": task["l4_request"]["dialog_id"], "summary": task["requirement"]},
            {"type": "template", "id": scenario["template_id"], "summary": TEMPLATES[scenario["template_id"]]["name"]},
            *[
                {"type": SOURCE_MATERIALS[ref]["type"], "id": ref, "summary": SOURCE_MATERIALS[ref]["summary"]}
                for ref in scenario["source_material_refs"]
            ],
        ],
        "prompt_summary": "按模板结构写文字初稿；引用资料必须可追溯；不得自行编造事实、金额、日期、法规条款。",
        "security_note": "完整提示词不在普通业务页展示，审计时按权限查看版本和摘要。",
    }


def build_model_dispatch(task: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    model_task_id = "MODEL-CP-" + uuid.uuid4().hex[:8].upper()
    return {
        "model_task_id": model_task_id,
        "routed_by": "1.5 大模型调度",
        "model_policy": "v0.1 使用本地 mock 文本生成；真实接入时由 1.5 决定模型、部署位置、是否允许出网和脱敏策略。",
        "model_type": "text_generation",
        "status_history": [
            {"status": "queued", "detail": "1.5 已接收内容生成请求。"},
            {"status": "running", "detail": "按提示词版本和上下文引用生成候选稿。"},
            {"status": "succeeded", "detail": "候选稿返回内容产出引擎核查。"},
        ],
        "candidate_count": len(scenario["mock_drafts"]) or 1,
    }


def build_cost_record(task: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    draft_count = max(1, len(scenario["mock_drafts"]))
    estimated_tokens = 1200 + draft_count * 450
    return {
        "cost_record_id": "COST-" + task["task_id"].split("-")[-1],
        "metered_by": "1.12 成本管控",
        "estimated_tokens": estimated_tokens,
        "candidate_count": draft_count,
        "estimated_cost": round(estimated_tokens / 1000 * 0.15, 2),
        "currency": "mock-credit",
        "warning": "high_review_cost" if draft_count > 3 else "normal",
    }


def build_drafts(task: dict[str, Any], scenario: dict[str, Any]) -> list[dict[str, Any]]:
    context = task.get("interface_context") or {}
    if context.get("capability_id") == "content_hot_case_reuse":
        return build_hot_case_reuse_drafts(task, scenario, context)
    drafts = []
    for index, draft in enumerate(scenario["mock_drafts"], start=1):
        drafts.append(
            {
                "draft_id": f"DRAFT-{task['task_id'].split('-')[-1]}-{index:02d}",
                "title": _render_text(draft["title"], task),
                "sections": [
                    {**section, "body": _render_text(section.get("body", ""), task)}
                    for section in draft.get("sections", [])
                ],
                "citations": scenario["source_material_refs"],
                "unresolved_questions": draft.get("unresolved_questions", []),
                "label_policy": "AI 生成待审核" if scenario["exit_policy"] != "direct_delivery" else "AI 生成内部初稿",
            }
        )
    return drafts


def _render_text(text: str, task: dict[str, Any]) -> str:
    requirement = (task.get("requirement") or "").strip()
    short_requirement = requirement[:160] + ("..." if len(requirement) > 160 else "")
    return text.replace("{requirement}", short_requirement)


def build_hot_case_reuse_drafts(task: dict[str, Any], scenario: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    batch_index = context.get("batch_index") or 1
    hot_case_refs = context.get("hot_case_refs") or ["HOT-CASE-001"]
    stage = context.get("hot_case_stage") or context.get("reuse_mode") or "hot_case_batch"
    stage_label = "打样" if stage == "sample" or batch_index == 0 else f"第 {batch_index} 版"
    skill_refs = context.get("skill_refs") or ["SKILL-HOT-CASE-PATTERN-001", "SKILL-HOT-CASE-STANDARD-001"]
    brief = task.get("requirement") or "智能监测设备爆款案例复用任务"
    return [
        {
            "draft_id": f"DRAFT-{task['task_id'].split('-')[-1]}-HOT-{int(batch_index):02d}",
            "title": f"爆款案例复用文案{stage_label}",
            "sections": [
                {
                    "heading": "复用策略",
                    "body": f"参考 {', '.join(hot_case_refs)} 的标题节奏、场景痛点和行动号召方式，取用技能 {', '.join(skill_refs)}，但不直接照搬原文；围绕当前任务“{brief[:80]}”生成可交给多媒体承接的文案骨架。",
                },
                {
                    "heading": "标题结构",
                    "body": "主标题突出“远程监测 + 异常提醒 + 减少重复巡检”；副标题强调种植基地场景和管理效率提升，避免绝对化承诺。",
                },
                {
                    "heading": "卖点结构",
                    "body": "第一层写设备能监测关键环境数据；第二层写异常状态及时提醒；第三层写巡检辅助和数据可追溯。每个卖点都需对应产品资料或知识库引用。",
                },
                {
                    "heading": "多媒体承接提示",
                    "body": "海报画面建议使用温室/种植基地真实场景、设备主体、数据面板和品牌 Logo 位置；多媒体只负责画面方案、版式和提示词，不重新创作正文。",
                },
            ],
            "citations": ["HOT-CASE-001", *scenario["source_material_refs"]],
            "unresolved_questions": ["请确认爆款案例是否已通过入库审核，正式联调时应使用真实 hot_case_id。"],
            "label_policy": "AI 生成内部初稿",
        }
    ]


def build_quality_report(task: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    template = TEMPLATES[scenario["template_id"]]
    draft_sections = {section["heading"] for draft in task.get("drafts", []) for section in draft.get("sections", [])}
    missing_sections = [name for name in template["required_sections"] if name not in draft_sections]
    return {
        "checked_by": "内容产出引擎规则核查 mock",
        "template_required_sections": template["required_sections"],
        "missing_sections": missing_sections,
        "source_refs_checked": scenario["source_material_refs"],
        "number_policy": "稿件中的数字、金额、日期、法规条款仅允许来自输入或依据资料。",
        "risk_level": scenario["risk_level"],
        "review_required": scenario["exit_policy"] != "direct_delivery",
        "result": "needs_human_review" if scenario["exit_policy"] != "direct_delivery" else "draft_can_return",
        "note": "v0.1 做结构化核查，不做真实事实真伪判断。",
    }


def build_labels(task: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        "content_id": result_id_for_task(task),
        "visible_label": "AI 生成待审核" if scenario["exit_policy"] != "direct_delivery" else "AI 生成内部初稿",
        "metadata_label": {
            "generated_by": "内容产出引擎 v0.2",
            "trace_id": task["trace_id"],
            "task_id": task["task_id"],
            "model_task_id": task.get("model_dispatch", {}).get("model_task_id"),
            "prompt_version": task.get("prompt_context", {}).get("prompt_version"),
            "template_id": scenario["template_id"],
        },
        "review_warning": "未经真人审核不得对外使用" if scenario["exit_policy"] != "direct_delivery" else "当前仅交付内部初稿，对外发布前仍需按业务规则确认。",
    }


def decide_exit_type(scenario: dict[str, Any]) -> str:
    if scenario["exit_policy"] == "direct_delivery":
        return "direct_delivery"
    if scenario["exit_policy"] == "pending_human_confirmation":
        return "pending_human_confirmation"
    return "unable_to_handle"


def build_approval(task: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    nodes = []
    for idx, position in enumerate(scenario["approval_template"], start=1):
        user_id = POSITION_TO_USER.get(position)
        user = USERS.get(user_id) if user_id else None
        nodes.append(
            {
                "node": idx,
                "position": position,
                "assignee_user_id": user_id,
                "assignee_name": user["name"] if user else "岗位无人",
                "status": "waiting" if idx == 1 else "not_started",
                "note": "流程执行引擎按固定模板组织真人确认，本原型只模拟状态返回。",
            }
        )
    return {
        "approval_id": "APR-" + uuid.uuid4().hex[:8].upper(),
        "organized_by": "流程执行引擎 mock",
        "current_node": 1 if nodes else 0,
        "status": "waiting" if nodes else "not_required",
        "nodes": nodes,
    }


def build_review_package(task: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        "package_id": "REVIEW-" + task["task_id"].split("-")[-1],
        "organized_by": "流程执行引擎 mock",
        "draft_ids": [draft["draft_id"] for draft in task.get("drafts", [])],
        "source_material_refs": scenario["source_material_refs"],
        "risk_notes": [
            "请核对事实、数字、期限、法规和对外表述。",
            "本引擎只生成文字初稿，不承担最终审核责任。",
        ],
        "required_confirm_positions": scenario["approval_template"],
    }


def build_semantic_summary(task: dict[str, Any], scenario: dict[str, Any]) -> str:
    if scenario["content_type"] == "marketing_bundle":
        return "围绕智能监测设备生成多类营销文字初稿，供产品推广人员完善。"
    if scenario["content_type"] == "legal_pleading":
        return "根据案件事实和文书结构生成法律文书草稿，必须律师审核后使用。"
    if scenario["content_type"] == "rectification_notice":
        return "根据隐患事实和法规依据生成整改通知书初稿，必须安全管理人员审核。"
    return "内容产出任务。"


def approve_current_node(task: dict[str, Any], approver_id: str, decision: str, reason: str | None = None) -> dict[str, Any]:
    if task.get("status") != "pending_human_confirmation" or not task.get("approval"):
        raise ValueError("当前任务不在待真人确认状态")
    approval = task["approval"]
    current = approval["current_node"]
    if current <= 0 or current > len(approval["nodes"]):
        raise ValueError("确认链节点异常")
    node = approval["nodes"][current - 1]
    record = check_permission(approver_id, result_id_for_task(task), "confirm_result", task_id=task["task_id"])
    task.setdefault("permission_records", []).append(record)
    if record["result"] != "allow":
        raise PermissionError(record["reason"])
    if node.get("assignee_user_id") and node["assignee_user_id"] != approver_id:
        raise PermissionError(f"当前节点应由 {node['assignee_name']} 处理，不能由 {USERS[approver_id]['name']} 代签。")
    node["handled_by"] = approver_id
    node["handled_by_name"] = USERS[approver_id]["name"]
    node["handled_at"] = datetime.now().isoformat(timespec="seconds")
    node["decision"] = decision
    node["reason"] = reason or ""
    if decision == "reject":
        node["status"] = "rejected"
        approval["status"] = "rejected"
        task["status"] = "rejected"
        task["review_status"] = "rejected"
        update_registry_status(task["registry_id"], "rejected", "rejected", reason or "真人审核驳回。")
        write_log(task["task_id"], approver_id, "review:reject", result_id_for_task(task), "deny", reason or "真人审核驳回。", layer="L2-流程执行")
        return task
    node["status"] = "approved"
    if current < len(approval["nodes"]):
        approval["current_node"] = current + 1
        approval["nodes"][current]["status"] = "waiting"
        approval["status"] = "waiting"
        task["review_status"] = "partially_approved"
    else:
        approval["status"] = "approved"
        task["status"] = "completed"
        task["exit_type"] = "confirmed_delivery"
        task["review_status"] = "approved"
        task["blocking_reason"] = None
        update_registry_status(task["registry_id"], "completed", "approved", "真人确认链已全部通过。")
        write_log(task["task_id"], approver_id, "review:approve", result_id_for_task(task), "allow", "真人确认链已全部通过，结果可交付。", layer="L2-流程执行")
    return task


def freeze_task(task: dict[str, Any], actor_id: str, reason: str) -> dict[str, Any]:
    record = check_permission(actor_id, result_id_for_task(task), "freeze_result", task_id=task["task_id"])
    task.setdefault("permission_records", []).append(record)
    if record["result"] != "allow":
        raise PermissionError(record["reason"])
    task["status"] = "frozen"
    task["blocking_reason"] = reason
    if task.get("registry_id"):
        update_registry_status(task["registry_id"], "frozen", task.get("review_status", "unknown"), reason)
    write_log(task["task_id"], actor_id, "result:freeze", result_id_for_task(task), "allow", reason, layer="L1-审计")
    return task
