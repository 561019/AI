from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import time
from pathlib import Path
from typing import Any


def write_verification_report(project_root: Path, result: dict[str, Any]) -> dict[str, Any]:
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    report_dir = project_root / "docs" / "evidence" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "module": "L1 1.14 执行沙箱",
        "runtime": "DockerTemplateExecutor",
        "generated_at": generated_at,
        "source": "POST /api/verification/report",
        "result": result,
    }
    json_rel = f"docs/evidence/reports/verification-report-{stamp}.json"
    md_rel = f"docs/evidence/reports/verification-report-{stamp}.md"
    (project_root / json_rel).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (project_root / md_rel).write_text(render_markdown_report(payload), encoding="utf-8")
    return {
        "status": "done",
        "generated_at": generated_at,
        "summary": result.get("summary", {}),
        "json": json_rel,
        "markdown": md_rel,
        "results_count": len(result.get("results", [])),
    }


def list_verification_reports(project_root: Path) -> dict[str, Any]:
    report_dir = project_root / "docs" / "evidence" / "reports"
    reports = []
    if report_dir.exists():
        paths = list(report_dir.glob("verification-report-*.json")) + list(report_dir.glob("concurrency-report-*.json"))
        for path in sorted(paths, reverse=True):
            rel = path.relative_to(project_root).as_posix()
            md_path = path.with_suffix(".md")
            stat = path.stat()
            reports.append(
                {
                    "type": "concurrency" if path.name.startswith("concurrency-report-") else "verification",
                    "json": rel,
                    "markdown": md_path.relative_to(project_root).as_posix() if md_path.exists() else None,
                    "size_bytes": stat.st_size,
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                }
            )
    return {"reports": reports, "count": len(reports)}


def write_concurrency_report(project_root: Path, service: Any, count: int = 3) -> dict[str, Any]:
    count = max(1, min(int(count), 6))
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    report_dir = project_root / "docs" / "evidence" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [pool.submit(run_concurrency_task, service, idx) for idx in range(count)]
        results = [future.result() for future in as_completed(futures)]
    results.sort(key=lambda item: item["index"])
    duration_ms = int((time.perf_counter() - started) * 1000)
    success = [item for item in results if item.get("ok")]
    failed = [item for item in results if not item.get("ok")]
    payload = {
        "module": "L1 1.14 执行沙箱",
        "runtime": "DockerTemplateExecutor",
        "generated_at": generated_at,
        "source": "POST /api/verification/concurrency-report",
        "summary": {
            "requested": count,
            "success": len(success),
            "failed": len(failed),
            "duration_ms": duration_ms,
            "max_workers": count,
        },
        "scenario": {
            "scenario_id": "s19_over_stock_warning",
            "actor": "sales-user",
            "expected_status": "warning",
            "expected_over_qty": 40,
        },
        "results": results,
    }

    json_rel = f"docs/evidence/reports/concurrency-report-{stamp}.json"
    md_rel = f"docs/evidence/reports/concurrency-report-{stamp}.md"
    (project_root / json_rel).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (project_root / md_rel).write_text(render_concurrency_markdown(payload), encoding="utf-8")
    return {
        "status": "done" if not failed else "partial",
        "generated_at": generated_at,
        "summary": payload["summary"],
        "json": json_rel,
        "markdown": md_rel,
        "results_count": len(results),
    }


def run_concurrency_task(service: Any, index: int) -> dict[str, Any]:
    payload = {
        "scenario_id": "s19_over_stock_warning",
        "actor": "sales-user",
        "agent": f"concurrency-agent-{index + 1}",
        "timeout_seconds": 10,
        "memory_mb": 512,
        "cpu_cores": 1,
        "input": {},
    }
    started = time.perf_counter()
    try:
        task = service.create_task(payload)
        result = ((task.get("result") or {}).get("payload") or {}) if isinstance(task, dict) else {}
        ok = (
            task.get("status") == "success"
            and task.get("executor") == "DockerTemplateExecutor"
            and result.get("status") == "warning"
            and float(result.get("over_qty", -1)) == 40.0
        )
        return {
            "index": index + 1,
            "ok": ok,
            "task_id": task.get("id"),
            "status": task.get("status"),
            "executor": task.get("executor"),
            "duration_ms": task.get("duration_ms"),
            "wall_ms": int((time.perf_counter() - started) * 1000),
            "business_result": {
                "inventory": result.get("inventory"),
                "total_order_qty": result.get("total_order_qty"),
                "over_qty": result.get("over_qty"),
                "status": result.get("status"),
            },
        }
    except Exception as exc:
        return {
            "index": index + 1,
            "ok": False,
            "status": "error",
            "error": str(exc),
            "wall_ms": int((time.perf_counter() - started) * 1000),
        }


def render_markdown_report(payload: dict[str, Any]) -> str:
    result = payload.get("result", {})
    summary = result.get("summary", {})
    lines = [
        "# 现场验证报告",
        "",
        f"生成时间：{payload.get('generated_at')}",
        "",
        "## 交付口径",
        "",
        "```text",
        "Docker 运行时的 L1 1.14 执行沙箱能力包",
        "```",
        "",
        "Cube Sandbox 是未来更强隔离选项，不作为当前 Docker 交付阻塞。",
        "",
        "## 汇总",
        "",
        f"- 通过：`{summary.get('passed', 0)}`",
        f"- 失败：`{summary.get('failed', 0)}`",
        "",
        "## 验证项",
        "",
    ]
    for item in result.get("results", []):
        lines.extend(
            [
                f"### {item.get('title') or item.get('id')}",
                "",
                f"- 状态：`{item.get('status')}`",
                f"- 证明点：{item.get('claim', '-')}",
                f"- 结论：{item.get('detail', '-')}",
                f"- 命令/API：`{single_line(item.get('command', '-'))}`",
                "",
            ]
        )
    lines.extend(
        [
            "## 说明",
            "",
            "本报告由服务端实时运行 `/api/verification/run {\"case_id\":\"all\"}` 同等验证逻辑后生成。",
            "报告文件用于交付复查；详细 stdout/stderr 和结构化证据见同名 JSON 文件。",
            "",
        ]
    )
    return "\n".join(lines)


def render_concurrency_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    scenario = payload.get("scenario", {})
    lines = [
        "# 并发调用测试报告",
        "",
        f"生成时间：{payload.get('generated_at')}",
        "",
        "## 交付口径",
        "",
        "```text",
        "Docker 运行时的 L1 1.14 执行沙箱能力包",
        "```",
        "",
        "## 测试目标",
        "",
        "验证后续 L2 平台按小批量并发方式调用执行沙箱时，任务能够分别进入 Docker 沙箱、完成业务计算并留下任务记录。",
        "",
        "## 汇总",
        "",
        f"- 请求任务数：`{summary.get('requested', 0)}`",
        f"- 成功：`{summary.get('success', 0)}`",
        f"- 失败：`{summary.get('failed', 0)}`",
        f"- 总耗时：`{summary.get('duration_ms', 0)} ms`",
        f"- 并发数：`{summary.get('max_workers', 0)}`",
        "",
        "## 场景",
        "",
        f"- 场景：`{scenario.get('scenario_id')}`",
        f"- 用户：`{scenario.get('actor')}`",
        f"- 预期：`{scenario.get('expected_status')}`，超库存 `{scenario.get('expected_over_qty')}` 吨",
        "",
        "## 任务结果",
        "",
    ]
    for item in payload.get("results", []):
        result = item.get("business_result", {})
        lines.extend(
            [
                f"### 任务 {item.get('index')}",
                "",
                f"- 状态：`{item.get('status')}`",
                f"- 通过：`{item.get('ok')}`",
                f"- 任务编号：`{item.get('task_id', '-')}`",
                f"- 执行器：`{item.get('executor', '-')}`",
                f"- 墙钟耗时：`{item.get('wall_ms', 0)} ms`",
                f"- 业务结果：库存 `{result.get('inventory', '-')}`，订单 `{result.get('total_order_qty', '-')}`，超库存 `{result.get('over_qty', '-')}`，状态 `{result.get('status', '-')}`",
                "",
            ]
        )
    lines.extend(
        [
            "## 说明",
            "",
            "这是保守小并发测试，默认 3 个任务，接口限制最多 6 个任务，避免给演示服务器造成不必要压力。",
            "它不是生产压测，只用于证明本 L1 能力包可以被上层模块小批量调用并形成可复查报告。",
            "",
        ]
    )
    return "\n".join(lines)


def single_line(value: Any) -> str:
    return " ".join(str(value).split())
