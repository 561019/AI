from __future__ import annotations

from app.context_engineering import compact_session_context, estimate_context_payload
from app.context_memory import create_context_memory, list_context_memories
from app.db import init_db
from app.handoff import close_session
from app.langfuse_platform import list_prompt_run_traces, score_prompt_run_trace
from app.prompts import create_prompt_template, create_prompt_version, list_prompt_versions, publish_prompt_version
from app.sessions import create_session, list_capacity_events, update_session_capacity, update_session_notes
from app.sync_packages import get_latest_sync_package, list_sync_packages, upgrade_sync_package
from app.utils import new_id


def main() -> None:
    init_db()
    suffix = new_id("smoke")
    project_id = f"p_{suffix}"
    prompt_code = f"smoke_prompt_{suffix}"

    memory = create_context_memory(
        {
            "scope_level": "project",
            "scope_id": project_id,
            "context_type": "confirmed_decision",
            "title": "Smoke project decision",
            "summary": "Use Langfuse as the LLMOps main platform and self-build business rules.",
            "content": "Harness9 is only used for Context Engineering ideas.",
            "created_by": "u_smoke",
        }
    )
    memories = list_context_memories(
        {"scope_level": ["project"], "scope_id": [project_id], "q": ["Langfuse"]},
        "u_smoke",
    )

    template = create_prompt_template(
        {
            "prompt_code": prompt_code,
            "scope_level": "project",
            "scope_id": project_id,
            "name": "Smoke Prompt",
            "owner_id": "u_smoke",
        }
    )
    version = create_prompt_version(
        template["id"],
        {
            "content": "Summarize this context: {{context}}",
            "variables_schema": {"context": "string"},
            "change_note": "Initial smoke version",
            "created_by": "u_smoke",
            "platform_binding": {
                "platform": "langfuse",
                "platform_prompt_name": "smoke-context-summary",
                "platform_version": "v1",
                "sync_status": "planned",
            },
        },
    )
    publish_prompt_version(version["id"], {"actor_id": "u_smoke"})

    report_template = create_prompt_template(
        {
            "prompt_code": "work_report",
            "scope_level": "project",
            "scope_id": project_id,
            "name": "工作汇报生成指令",
            "owner_id": "u_smoke",
        }
    )
    report_version = create_prompt_version(
        report_template["id"],
        {
            "content": "基于会话摘要、决策、待办和风险生成阶段性工作汇报。",
            "variables_schema": {"session": "object"},
            "created_by": "u_smoke",
            "platform_binding": {
                "platform": "langfuse",
                "platform_prompt_name": "work-report",
                "platform_version": "v1",
            },
        },
    )
    publish_prompt_version(report_version["id"], {"actor_id": "u_smoke"})

    handoff_template = create_prompt_template(
        {
            "prompt_code": "handoff_file",
            "scope_level": "project",
            "scope_id": project_id,
            "name": "工作交接文件生成指令",
            "owner_id": "u_smoke",
        }
    )
    handoff_version = create_prompt_version(
        handoff_template["id"],
        {
            "content": "生成给下一个对话框直接读取的工作交接文件。",
            "variables_schema": {"session": "object"},
            "created_by": "u_smoke",
            "platform_binding": {
                "platform": "langfuse",
                "platform_prompt_name": "handoff-file",
                "platform_version": "v1",
            },
        },
    )
    publish_prompt_version(handoff_version["id"], {"actor_id": "u_smoke"})

    sync_template = create_prompt_template(
        {
            "prompt_code": "sync_package_compress",
            "scope_level": "project",
            "scope_id": project_id,
            "name": "Sync Package Compress Instruction",
            "owner_id": "u_smoke",
        }
    )
    sync_version = create_prompt_version(
        sync_template["id"],
        {
            "content": "Merge the previous sync package and the latest work report into a new durable project context.",
            "variables_schema": {"previous_sync_package": "object", "work_report": "object"},
            "created_by": "u_smoke",
            "platform_binding": {
                "platform": "langfuse",
                "platform_prompt_name": "sync_package_compress",
                "platform_version": "v1",
            },
        },
    )
    publish_prompt_version(sync_version["id"], {"actor_id": "u_smoke"})

    estimate = estimate_context_payload({"text": "x" * 3200, "context_window": 1000})
    session = create_session(
        {
            "project_id": project_id,
            "title": "阶段一单框闭环",
            "capacity_limit": 1000,
            "used_units": 760,
            "summary": "已完成 Langfuse 主平台决策、Context Engineering 范围收窄和业务闭环骨架。",
            "open_todos": ["完善前端管理台", "接入真实 Langfuse API"],
            "decisions": ["Langfuse 作为 LLMOps 主平台", "harness9 只取 Context Engineering"],
            "risks": ["后续需要真实 LLM 生成质量评估"],
            "created_by": "u_smoke",
        }
    )
    warned = update_session_capacity(session["id"], {"delta_units": 60, "actor_id": "u_smoke"})
    forced = update_session_capacity(session["id"], {"delta_units": 40, "actor_id": "u_smoke"})
    update_session_notes(
        session["id"],
        {
            "summary": "阶段一闭环骨架已经可运行。",
            "open_todos": ["完善前端管理台", "接入真实 Langfuse API"],
            "updated_by": "u_smoke",
        },
    )
    compaction = compact_session_context(
        session["id"],
        {
            "summary": "压缩摘要：保留 Langfuse 主平台、Context Engineering 和自研业务闭环决策。",
            "tokens_before": 860,
            "tokens_after": 80,
            "messages_before": 24,
            "messages_after": 4,
            "actor_id": "u_smoke",
        },
    )
    capacity_events = list_capacity_events(session["id"], "u_smoke")
    close_result = close_session(session["id"], {"actor_id": "u_smoke"})
    sync_package = upgrade_sync_package(
        project_id,
        {"work_report_id": close_result["work_report"]["id"], "actor_id": "u_smoke"},
    )
    latest_sync_package = get_latest_sync_package(project_id, "u_smoke")
    sync_packages = list_sync_packages(project_id, {}, "u_smoke")
    traces = list_prompt_run_traces({"session_id": [session["id"]]})
    scored_trace = score_prompt_run_trace(
        traces[0]["id"],
        {"score": 0.92, "score_reason": "Smoke output generated and linked to prompt version.", "actor_id": "u_smoke"},
    )
    versions = list_prompt_versions(template["id"], "u_smoke")
    print(
        {
            "memory_id": memory["id"],
            "memory_count": len(memories),
            "template_id": template["id"],
            "version_id": version["id"],
            "version_count": len(versions),
            "platform_binding_count": len(versions[0].get("platform_bindings", [])),
            "context_estimate_status": estimate["status"],
            "session_id": session["id"],
            "warning_status": warned["status"],
            "handoff_status": forced["status"],
            "compaction_id": compaction["id"],
            "capacity_event_count": len(capacity_events),
            "work_report_id": close_result["work_report"]["id"],
            "handoff_file_id": close_result["handoff_file"]["id"],
            "sync_package_id": sync_package["id"],
            "sync_package_version": sync_package["version_no"],
            "latest_sync_package_id": latest_sync_package["id"],
            "sync_package_count": len(sync_packages),
            "trace_count": len(traces),
            "scored_trace_id": scored_trace["id"],
            "scored_trace_score": scored_trace["score"],
        }
    )


if __name__ == "__main__":
    main()
