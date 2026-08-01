from __future__ import annotations

from app import chat, handoff, handoff_runs, sync_packages
from app.chat import chat_with_session, list_session_messages
from app.db import init_db
from app.sessions import create_session, get_session
from app.utils import new_id


def main() -> None:
    init_db()
    handoff.use_remote_generation = lambda: False
    sync_packages.use_remote_generation = lambda: False
    handoff_runs.generate_llm_text = lambda **_: {
        "content": "这是写入新对话框的 AI 回复。",
        "provider": "smoke",
        "model": "fake-model",
        "response_id": "resp_smoke",
        "usage": {},
    }

    suffix = new_id("auto")
    project_id = f"p_{suffix}"
    session = create_session(
        {
            "project_id": project_id,
            "title": "自动传承测试",
            "capacity_limit": 1000,
            "used_units": 700,
            "summary": "用于验证首次跨 85% 自动传承。",
            "open_todos": ["验证分步 API"],
            "decisions": ["自动传承只发生一次"],
            "risks": [],
            "created_by": "u_auto",
        }
    )

    chat_result = chat_with_session(
        session["id"],
        {
            "message": "这是一段用于推动容量跨过阈值的用户输入。" + "上下文" * 70,
            "actor_id": "u_auto",
            "estimated_reply_units": 300,
        },
    )
    assert chat_result["auto_handoff"] is True
    run_id = chat_result["handoff_run_id"]
    old_messages = list_session_messages(session["id"], "u_auto")
    assert [item["role"] for item in old_messages] == ["user"]

    reply_result = handoff_runs.write_handoff_reply(run_id, {"actor_id": "u_auto"})
    new_session_id = reply_result["new_session"]["id"]
    new_messages = list_session_messages(new_session_id, "u_auto")
    assert [item["role"] for item in new_messages] == ["assistant"]

    report_result = handoff_runs.generate_run_work_report(run_id, {"actor_id": "u_auto"})
    assert report_result["work_report"]["id"]
    handoff_result = handoff_runs.generate_run_handoff_file(run_id, {"actor_id": "u_auto"})
    assert handoff_result["handoff_file"]["id"]
    sync_result = handoff_runs.upgrade_run_sync_package(run_id, {"actor_id": "u_auto"})
    assert sync_result["sync_package"]["id"]
    complete_result = handoff_runs.complete_handoff_run(run_id, {"actor_id": "u_auto"})
    old_session = complete_result["old_session"]
    assert old_session["auto_handoff_done"] is True
    assert old_session["next_session_id"] == new_session_id

    chat.generate_llm_text = lambda **_: {
        "content": "传承完成后，旧对话框在达到 100% 前仍可继续对话。",
        "provider": "smoke",
        "model": "fake-model",
        "response_id": "resp_old_session",
        "usage": {},
    }
    continued = chat_with_session(
        session["id"],
        {"message": "继续在旧对话框对话", "actor_id": "u_auto"},
    )
    assert continued["auto_handoff"] is False
    assert continued["reply"]
    assert continued["session"]["auto_handoff_done"] is True
    assert continued["session"]["locked"] is False

    lock_session = create_session(
        {
            "project_id": project_id,
            "title": "锁定测试",
            "capacity_limit": 1000,
            "used_units": 950,
            "summary": "用于验证 100% 锁定。",
            "created_by": "u_auto",
        }
    )
    locked = chat_with_session(
        lock_session["id"],
        {"message": "超过容量" * 80, "actor_id": "u_auto"},
    )
    assert locked["locked"] is True
    assert get_session(lock_session["id"], "u_auto")["locked"] is True

    print(
        {
            "handoff_run_id": run_id,
            "old_session_id": session["id"],
            "new_session_id": new_session_id,
            "work_report_id": complete_result["work_report"]["id"],
            "handoff_file_id": complete_result["handoff_file"]["id"],
            "sync_package_id": complete_result["sync_package"]["id"],
            "locked_session_id": lock_session["id"],
        }
    )


if __name__ == "__main__":
    main()
