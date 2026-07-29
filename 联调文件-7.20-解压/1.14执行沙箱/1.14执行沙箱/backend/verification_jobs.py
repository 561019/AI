from __future__ import annotations

import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.verification import run_all_verification_cases, run_verification_case


_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
_max_jobs = 40


def start_verification_job(project_root: Path, service: Any, case_id: str) -> dict[str, Any]:
    job_id = f"verify-{uuid.uuid4().hex[:12]}"
    now = utc_now()
    job = {
        "id": job_id,
        "case_id": case_id,
        "status": "queued",
        "created_at": now,
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
        "events": [],
        "result": None,
        "error": None,
    }
    with _lock:
        _jobs[job_id] = job
        trim_jobs()
    thread = threading.Thread(target=run_job, args=(project_root, service, job_id), daemon=True)
    thread.start()
    return snapshot(job_id)


def get_verification_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        return deepcopy(job) if job else None


def run_job(project_root: Path, service: Any, job_id: str) -> None:
    started = time.monotonic()
    update_job(job_id, status="running", started_at=utc_now())
    append_event(job_id, "job_started", "验收任务已启动", "后端线程开始执行真实验证逻辑。", {})

    def progress(kind: str, title: str, detail: str, data: dict[str, Any]) -> None:
        append_event(job_id, kind, title, detail, data)

    try:
        job = get_verification_job(job_id) or {}
        case_id = str(job.get("case_id", "all"))
        result = (
            run_all_verification_cases(project_root, service, progress)
            if case_id == "all"
            else run_verification_case(project_root, service, case_id, progress)
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        append_event(job_id, "job_finished", "验收任务完成", f"后端执行结束，总耗时 {duration_ms} ms。", {"duration_ms": duration_ms})
        update_job(job_id, status="completed", finished_at=utc_now(), duration_ms=duration_ms, result=result)
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        append_event(job_id, "job_failed", "验收任务失败", str(exc), {})
        update_job(job_id, status="failed", finished_at=utc_now(), duration_ms=duration_ms, error=str(exc))


def append_event(job_id: str, kind: str, title: str, detail: str, data: dict[str, Any]) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job["events"].append({
            "seq": len(job["events"]) + 1,
            "at": utc_now(),
            "kind": kind,
            "title": title,
            "detail": detail,
            "data": data,
        })


def update_job(job_id: str, **values: Any) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job.update(values)


def snapshot(job_id: str) -> dict[str, Any]:
    job = get_verification_job(job_id)
    if not job:
        raise KeyError(job_id)
    return job


def trim_jobs() -> None:
    if len(_jobs) <= _max_jobs:
        return
    removable = sorted(_jobs.values(), key=lambda item: item["created_at"])
    for item in removable[: len(_jobs) - _max_jobs]:
        if item["status"] in {"completed", "failed"}:
            _jobs.pop(item["id"], None)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
