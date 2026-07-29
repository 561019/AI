from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable


ProgressReporter = Callable[[str, str, str, dict[str, Any]], None]
_progress_reporter: ContextVar[ProgressReporter | None] = ContextVar("verification_progress", default=None)


CASES = [
    {
        "id": "docker_runtime",
        "title": "Docker 真隔离运行时",
        "claim": "沙箱任务由 Linux Docker 容器承载，不再是 Windows 本地函数模拟。",
        "expected": "Docker daemon 可用，并能返回服务端版本。",
    },
    {
        "id": "docker_task",
        "title": "任务在 Docker 沙箱中执行",
        "claim": "业务任务进入 DockerTemplateExecutor，产出真实任务编号和业务结果。",
        "expected": "任务状态为 success，executor 为 DockerTemplateExecutor。",
    },
    {
        "id": "host_file_isolation",
        "title": "宿主机文件隔离",
        "claim": "容器只能看到挂载进去的目录，不能读取沙箱外的宿主机文件，也不能写只读代码目录。",
        "expected": "读取未挂载宿主机文件失败，写 /app 失败。",
    },
    {
        "id": "resource_timeout",
        "title": "跑飞任务自动停止",
        "claim": "死循环容器会被超时逻辑停止，并带有 CPU/内存限制。",
        "expected": "死循环容器超时后被 docker rm -f 停止。",
    },
    {
        "id": "network_default_deny",
        "title": "默认禁止出站",
        "claim": "容器使用 --network none，默认不能访问外网。",
        "expected": "容器内访问 https://example.com 失败。",
    },
    {
        "id": "egress_allowlist_gateway",
        "title": "域名级出站白名单网关",
        "claim": "任务容器不能直接出网，只能通过 egress-proxy 访问白名单域名。",
        "expected": "受控白名单测试域名通过，非白名单域名被拒绝，绕过代理直连失败。",
    },
    {
        "id": "browser_sandbox",
        "title": "浏览器沙箱出站验证",
        "claim": "Headless Chromium 在独立 Docker 浏览器容器里运行，不能直接出网，只能经白名单网关访问允许域名。",
        "expected": "受控白名单测试页真实加载，非白名单域名被网关拒绝，绕过代理直连失败。",
    },
    {
        "id": "permission_denial",
        "title": "权限不足前置拦截",
        "claim": "没有权限的角色不会正常执行敏感场景。",
        "expected": "sales-user 只有库存和订单读取权限，执行发票核销时因缺少 invoice:read 和 receipt:read 被拦截。",
    },
    {
        "id": "credential_injection",
        "title": "凭据注入不暴露明文",
        "claim": "安全合规侧持有明文凭据，任务容器只拿到短期句柄，不能从环境变量、命令行或挂载目录读到明文密钥。",
        "expected": "任务容器可以通过 broker 使用凭据能力，但输出、环境、命令行和文件扫描都不包含明文密钥。",
    },
    {
        "id": "e2b_like_adapter",
        "title": "E2B-like Docker 适配器",
        "claim": "在不依赖 Cube 的情况下，提供 create/run/query/destroy 形态的沙箱会话接口，底层仍由 Docker 沙箱执行。",
        "expected": "能创建会话、运行一个 Docker 沙箱任务、查询会话任务记录，并销毁会话。",
    },
    {
        "id": "hanhe_role_scenario_e2e",
        "title": "汉和岗位场景端到端证明",
        "claim": "用销售/供应链真实岗位场景证明本 L1 沙箱模块能承接任务、隔离执行、输出结果、记录权限/成本/审计证据。",
        "expected": "sales-user 运行跨部门超库存预警成功，输出 90 吨订单、50 吨库存、超 40 吨预警，并保留 Docker 与平台链路证据。",
    },
    {
        "id": "hanhe_finance_invoice_e2e",
        "title": "汉和财务发票核销端到端证明",
        "claim": "用财务岗位场景证明沙箱能接收 ERP 发票/入库单数据，在 Docker 内完成核销匹配，并留下权限、成本和审计证据。",
        "expected": "demo-user 运行发票核销成功，至少一张发票匹配、一张发票异常，并保留 Docker 与平台链路证据。",
    },
    {
        "id": "hanhe_purchase_plan_e2e",
        "title": "汉和采购计划端到端证明",
        "claim": "用采购计划场景证明沙箱能接收历史采购和库存数据，在 Docker 内计算预测需求和建议采购量。",
        "expected": "demo-user 运行采购计划分析成功，输出预测需求和大于 0 的建议采购量，并保留 Docker 与平台链路证据。",
    },
]


def list_verification_cases() -> list[dict[str, str]]:
    return CASES


def run_verification_case(project_root: Path, service: Any, case_id: str, progress: ProgressReporter | None = None) -> dict[str, Any]:
    runners = {
        "docker_runtime": lambda: verify_docker_runtime(project_root),
        "docker_task": lambda: verify_docker_task(service),
        "host_file_isolation": lambda: verify_host_file_isolation(project_root),
        "resource_timeout": lambda: verify_resource_timeout(project_root),
        "network_default_deny": lambda: verify_network_default_deny(project_root),
        "egress_allowlist_gateway": lambda: verify_egress_allowlist_gateway(project_root),
        "browser_sandbox": lambda: verify_browser_sandbox(project_root),
        "permission_denial": lambda: verify_permission_denial(service),
        "credential_injection": lambda: verify_credential_injection(project_root),
        "e2b_like_adapter": lambda: verify_e2b_like_adapter(project_root, service),
        "hanhe_role_scenario_e2e": lambda: verify_hanhe_role_scenario_e2e(service),
        "hanhe_finance_invoice_e2e": lambda: verify_hanhe_finance_invoice_e2e(service),
        "hanhe_purchase_plan_e2e": lambda: verify_hanhe_purchase_plan_e2e(service),
    }
    if case_id not in runners:
        raise ValueError(f"unknown verification case: {case_id}")
    meta = next(item for item in CASES if item["id"] == case_id)
    token = _progress_reporter.set(progress) if progress else None
    try:
        emit_progress("case_started", "开始现场验证", f"执行 {meta['title']} 对应的后端验证函数。", {"case_id": case_id})
        result = runners[case_id]()
        emit_progress(
            "case_finished",
            "验证完成" if result.get("status") == "passed" else "验证未通过",
            str(result.get("detail", "")),
            {"case_id": case_id, "status": result.get("status")},
        )
        return {**meta, **result}
    finally:
        if token is not None:
            _progress_reporter.reset(token)


def run_all_verification_cases(project_root: Path, service: Any, progress: ProgressReporter | None = None) -> dict[str, Any]:
    results = [run_verification_case(project_root, service, item["id"], progress) for item in CASES]
    return {
        "summary": {
            "passed": sum(1 for item in results if item["status"] == "passed"),
            "failed": sum(1 for item in results if item["status"] == "failed"),
        },
        "results": results,
    }


def verify_docker_runtime(project_root: Path) -> dict[str, Any]:
    docker = require_docker()
    command = [docker, "info", "--format", "{{.ServerVersion}}"]
    proc = run(command, timeout=10)
    return evidence(
        "passed" if proc["returncode"] == 0 else "failed",
        command,
        proc,
        "Docker server is available." if proc["returncode"] == 0 else "Docker server is not available.",
    )


def verify_docker_task(service: Any) -> dict[str, Any]:
    emit_progress("task_started", "创建业务任务", "提交销售/供应链超库存预警任务，进入平台前置链路和 Docker 执行器。", {})
    task = service.create_task({"scenario_id": "s19_over_stock_warning", "actor": "sales-user", "agent": "acceptance-agent", "input": {}})
    emit_progress("task_finished", "业务任务返回", f"任务 {task.get('id', '-')} 状态为 {task.get('status', '-')}，执行器为 {task.get('executor', '-')}。", {"task_id": task.get("id"), "executor": task.get("executor")})
    ok = task.get("status") == "success" and task.get("executor") == "DockerTemplateExecutor"
    return {
        "status": "passed" if ok else "failed",
        "detail": "Docker task returned a business result." if ok else "Docker task did not complete successfully.",
        "command": "POST /api/tasks scenario=s19_over_stock_warning actor=sales-user",
        "evidence": {
            "task_id": task.get("id"),
            "status": task.get("status"),
            "executor": task.get("executor"),
            "duration_ms": task.get("duration_ms"),
            "result": task.get("result"),
        },
    }


def verify_host_file_isolation(project_root: Path) -> dict[str, Any]:
    docker = require_docker()
    image = docker_image(project_root)
    sentinel = project_root.parent / f"host_secret_{uuid.uuid4().hex[:8]}.txt"
    sentinel.write_text("leadership-demo-secret", encoding="utf-8")
    emit_progress("probe_prepared", "准备越权探针", "已在沙箱挂载范围外创建临时秘密文件，容器不应看到它。", {"sentinel": sentinel.name})
    code = (
        "from pathlib import Path\n"
        f"secret=Path({str(sentinel)!r})\n"
        "if secret.exists(): raise SystemExit('host secret leaked')\n"
        "try:\n"
        "    Path('/app/write_probe.txt').write_text('bad')\n"
        "    raise SystemExit('read-only app mount is writable')\n"
        "except OSError:\n"
        "    pass\n"
        "print('PASS: secret not mounted; /app is read-only')\n"
    )
    command = [
        docker,
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m",
        "-v",
        f"{project_root}:/app:ro",
        "-w",
        "/app",
        image,
        "python",
        "-c",
        code,
    ]
    try:
        proc = run(command, timeout=15)
    finally:
        sentinel.unlink(missing_ok=True)
    return evidence(
        "passed" if proc["returncode"] == 0 else "failed",
        command,
        proc,
        "Container isolation probe passed." if proc["returncode"] == 0 else "Container isolation probe failed.",
    )


def verify_resource_timeout(project_root: Path) -> dict[str, Any]:
    docker = require_docker()
    image = docker_image(project_root)
    container_name = f"verify-timeout-{uuid.uuid4().hex[:8]}"
    emit_progress("container_prepared", "准备跑飞容器", "将启动死循环任务，并限制 CPU 0.5 核、内存 64 MB、最长运行 2 秒。", {"container_name": container_name, "cpu": "0.5", "memory": "64m", "timeout_seconds": 2})
    command = [
        docker,
        "run",
        "--rm",
        "--name",
        container_name,
        "--network",
        "none",
        "--cpus",
        "0.5",
        "--memory",
        "64m",
        image,
        "python",
        "-c",
        "while True: pass",
    ]
    try:
        proc = run(command, timeout=2)
        return evidence("failed", command, proc, "Runaway container exited before timeout; this is unexpected for the probe.")
    except subprocess.TimeoutExpired:
        emit_progress("timeout_triggered", "运行时长达到上限", "死循环容器超过 2 秒，后端开始强制清理。", {"container_name": container_name})
        cleanup = run([docker, "rm", "-f", container_name], timeout=10)
        return {
            "status": "passed",
            "detail": "Runaway container was stopped after timeout.",
            "command": shell_text(command),
            "evidence": {
                "timeout_seconds": 2,
                "container_name": container_name,
                "cleanup_command": shell_text([docker, "rm", "-f", container_name]),
                "cleanup_stdout": cleanup["stdout"],
                "cleanup_stderr": cleanup["stderr"],
                "cleanup_returncode": cleanup["returncode"],
            },
        }


def verify_network_default_deny(project_root: Path) -> dict[str, Any]:
    docker = require_docker()
    image = docker_image(project_root)
    command = [
        docker,
        "run",
        "--rm",
        "--network",
        "none",
        image,
        "python",
        "-c",
        "import urllib.request; urllib.request.urlopen('https://example.com', timeout=3)",
    ]
    proc = run(command, timeout=10)
    ok = proc["returncode"] != 0
    return evidence(
        "passed" if ok else "failed",
        command,
        proc,
        "Outbound network was blocked by --network none." if ok else "Container unexpectedly reached the network.",
    )


def verify_egress_allowlist_gateway(project_root: Path) -> dict[str, Any]:
    docker = require_docker()
    image = docker_image(project_root)
    suffix = uuid.uuid4().hex[:8]
    network = f"agent-egress-{suffix}"
    proxy = f"agent-egress-proxy-{suffix}"
    allowed_host = "sandbox-allow.test"
    blocked_host = "sandbox-blocked.test"
    commands: list[str] = []
    evidence_data: dict[str, Any] = {
        "network": network,
        "proxy_container": proxy,
        "allowed_host": allowed_host,
        "blocked_host": blocked_host,
    }
    try:
        create_network = [docker, "network", "create", "--internal", network]
        commands.append(shell_text(create_network))
        create_proc = run(create_network, timeout=15)
        evidence_data["create_network"] = create_proc
        if create_proc["returncode"] != 0:
            return {"status": "failed", "detail": "Could not create internal Docker network.", "command": "\n".join(commands), "evidence": evidence_data}

        proxy_cmd = [
            docker,
            "run",
            "-d",
            "--rm",
            "--name",
            proxy,
            "--network",
            network,
            "-v",
            f"{project_root}:/app:ro",
            "-w",
            "/app",
            image,
            "python",
            "backend/egress_gateway.py",
            "--allow",
            allowed_host,
            "--serve-local",
            allowed_host,
        ]
        commands.append(shell_text(proxy_cmd))
        proxy_proc = run(proxy_cmd, timeout=20)
        evidence_data["start_proxy"] = proxy_proc
        if proxy_proc["returncode"] != 0:
            return {"status": "failed", "detail": "Could not start egress proxy container.", "command": "\n".join(commands), "evidence": evidence_data}

        allowed_code = f"import urllib.request; print(urllib.request.urlopen('http://{allowed_host}', timeout=8).status)"
        allowed_cmd = [
            docker,
            "run",
            "--rm",
            "--network",
            network,
            "-e",
            "http_proxy=http://" + proxy + ":18080",
            image,
            "python",
            "-c",
            allowed_code,
        ]
        commands.append(shell_text(allowed_cmd))
        allowed = run(allowed_cmd, timeout=20)
        evidence_data["allow_sandbox_test"] = allowed

        blocked_code = f"import urllib.request; urllib.request.urlopen('http://{blocked_host}', timeout=8)"
        blocked_cmd = [
            docker,
            "run",
            "--rm",
            "--network",
            network,
            "-e",
            "http_proxy=http://" + proxy + ":18080",
            image,
            "python",
            "-c",
            blocked_code,
        ]
        commands.append(shell_text(blocked_cmd))
        blocked = run(blocked_cmd, timeout=20)
        evidence_data["block_non_allowlisted"] = blocked

        bypass_code = f"import urllib.request; urllib.request.urlopen('http://{allowed_host}', timeout=5)"
        bypass_cmd = [docker, "run", "--rm", "--network", network, image, "python", "-c", bypass_code]
        commands.append(shell_text(bypass_cmd))
        bypass = run(bypass_cmd, timeout=15)
        evidence_data["direct_bypass_attempt"] = bypass

        logs_cmd = [docker, "logs", proxy]
        commands.append(shell_text(logs_cmd))
        evidence_data["proxy_logs"] = run(logs_cmd, timeout=10)

        ok = allowed["returncode"] == 0 and blocked["returncode"] != 0 and bypass["returncode"] != 0
        return {
            "status": "passed" if ok else "failed",
            "detail": "Egress gateway allowed a controlled allowlisted test domain, blocked a non-allowlisted domain, and prevented direct bypass." if ok else "Egress gateway behavior did not match expectations.",
            "command": "\n".join(commands),
            "evidence": evidence_data,
        }
    finally:
        run([docker, "rm", "-f", proxy], timeout=10)
        run([docker, "network", "rm", network], timeout=10)


def verify_browser_sandbox(project_root: Path) -> dict[str, Any]:
    docker = require_docker()
    python_image = docker_image(project_root)
    browser_image = docker_browser_image(project_root)
    suffix = uuid.uuid4().hex[:8]
    network = f"agent-browser-{suffix}"
    proxy = f"agent-browser-proxy-{suffix}"
    allowed_host = "sandbox-allow.test"
    blocked_host = "sandbox-blocked.test"
    commands: list[str] = []
    evidence_data: dict[str, Any] = {
        "network": network,
        "proxy_container": proxy,
        "browser_image": browser_image,
        "python_image": python_image,
        "allowed_host": allowed_host,
        "blocked_host": blocked_host,
    }
    chrome_flags = (
        "mkdir -p /tmp/chrome/crash; "
        "chromium --headless --no-sandbox --disable-gpu --disable-dev-shm-usage "
        "--disable-crash-reporter --disable-breakpad --disable-background-networking "
        "--disable-sync --disable-default-apps --metrics-recording-only "
        "--safebrowsing-disable-auto-update --crash-dumps-dir=/tmp/chrome/crash "
        "--no-first-run --user-data-dir=/tmp/chrome"
    )

    def browser_command(script: str) -> list[str]:
        return [
            docker,
            "run",
            "--rm",
            "--memory",
            "768m",
            "--cpus",
            "1",
            "--network",
            network,
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,size=256m",
            "--tmpfs",
            "/run:rw,nosuid,size=64m",
            "--tmpfs",
            "/root:rw,nosuid,size=64m",
            "--tmpfs",
            "/var/tmp:rw,nosuid,size=64m",
            browser_image,
            "/bin/bash",
            "-lc",
            script,
        ]

    try:
        create_network = [docker, "network", "create", "--internal", network]
        commands.append(shell_text(create_network))
        create_proc = run(create_network, timeout=15)
        evidence_data["create_network"] = create_proc
        if create_proc["returncode"] != 0:
            return {"status": "failed", "detail": "Could not create internal Docker network for browser sandbox.", "command": "\n".join(commands), "evidence": evidence_data}

        proxy_cmd = [
            docker,
            "run",
            "-d",
            "--rm",
            "--name",
            proxy,
            "--network",
            network,
            "-v",
            f"{project_root}:/app:ro",
            "-w",
            "/app",
            python_image,
            "python",
            "backend/egress_gateway.py",
            "--allow",
            allowed_host,
            "--serve-local",
            allowed_host,
        ]
        commands.append(shell_text(proxy_cmd))
        proxy_proc = run(proxy_cmd, timeout=20)
        evidence_data["start_proxy"] = proxy_proc
        if proxy_proc["returncode"] != 0:
            return {"status": "failed", "detail": "Could not start egress proxy for browser sandbox.", "command": "\n".join(commands), "evidence": evidence_data}

        allowed_cmd = browser_command(f"{chrome_flags} --proxy-server=http://{proxy}:18080 --dump-dom http://{allowed_host}")
        commands.append(shell_text(allowed_cmd))
        allowed = compact_proc(run(allowed_cmd, timeout=45))
        evidence_data["browser_allow_sandbox_test"] = allowed

        blocked_cmd = browser_command(f"{chrome_flags} --proxy-server=http://{proxy}:18080 --dump-dom http://{blocked_host}")
        commands.append(shell_text(blocked_cmd))
        blocked = compact_proc(run(blocked_cmd, timeout=45))
        evidence_data["browser_block_non_allowlisted"] = blocked

        bypass_cmd = browser_command(f"{chrome_flags} --dump-dom http://{allowed_host}")
        commands.append(shell_text(bypass_cmd))
        bypass = compact_proc(run(bypass_cmd, timeout=45))
        evidence_data["browser_direct_bypass_attempt"] = bypass

        logs_cmd = [docker, "logs", proxy]
        commands.append(shell_text(logs_cmd))
        logs = run(logs_cmd, timeout=10)
        evidence_data["proxy_logs"] = compact_proc(logs, limit=5000)

        proxy_log_text = logs["stdout"] + logs["stderr"]
        bypass_text = bypass["stdout"] + bypass["stderr"]
        allowed_ok = "Sandbox Allowlist Probe" in allowed["stdout"]
        blocked_ok = f'"host": "{blocked_host}"' in proxy_log_text and '"allowed": false' in proxy_log_text
        bypass_ok = "Sandbox Allowlist Probe" not in bypass["stdout"] and ("ERR_" in bypass_text or "offline" in bypass_text.lower())
        evidence_data["assertions"] = {
            "allowlisted_page_loaded": allowed_ok,
            "non_allowlisted_blocked": blocked_ok,
            "direct_bypass_blocked": bypass_ok,
            "decision_basis": "Chromium page content plus egress proxy audit logs; Chromium may return code 0 after rendering a blocked or offline error page.",
        }
        ok = allowed_ok and blocked_ok and bypass_ok
        return {
            "status": "passed" if ok else "failed",
            "detail": "Browser container loaded a controlled allowlisted page through the gateway, hit a deny record for a non-allowlisted domain, and could not bypass the proxy." if ok else "Browser sandbox behavior did not match expectations.",
            "command": "\n".join(commands),
            "evidence": evidence_data,
        }
    finally:
        run([docker, "rm", "-f", proxy], timeout=10)
        run([docker, "network", "rm", network], timeout=10)


def verify_permission_denial(service: Any) -> dict[str, Any]:
    emit_progress("task_started", "提交越权任务", "销售用户尝试执行财务发票核销，用于验证权限前置拦截。", {})
    task = service.create_task({"scenario_id": "s04_invoice_matching", "actor": "sales-user", "agent": "acceptance-agent", "input": {}})
    error = json.dumps(task.get("result", {}), ensure_ascii=False)
    ok = task.get("status") == "denied" and "invoice:read" in error and "receipt:read" in error
    return {
        "status": "passed" if ok else "failed",
        "detail": "Permission denial path worked." if ok else "Permission denial path did not work.",
        "command": "POST /api/tasks scenario=s04_invoice_matching actor=sales-user",
        "evidence": {
            "task_id": task.get("id"),
            "status": task.get("status"),
            "executor": task.get("executor"),
            "error": task.get("result"),
            "security_compliance": task.get("platform_checks", {}).get("security_compliance"),
        },
    }


def verify_credential_injection(project_root: Path) -> dict[str, Any]:
    docker = require_docker()
    image = docker_image(project_root)
    suffix = uuid.uuid4().hex[:8]
    network = f"agent-cred-{suffix}"
    broker = f"agent-cred-broker-{suffix}"
    handle = f"handle-{uuid.uuid4().hex}"
    secret = f"vault-secret-{uuid.uuid4().hex}"
    emit_progress("credential_prepared", "生成短期凭据句柄", "明文密钥只交给 broker，任务容器只接收短期 handle。", {"credential_handle": handle})
    commands: list[str] = []
    evidence_data: dict[str, Any] = {
        "network": network,
        "broker_container": broker,
        "credential_handle": handle,
        "secret_policy": "plaintext secret is kept in broker container only; task container receives handle only",
    }
    try:
        create_network = [docker, "network", "create", "--internal", network]
        commands.append(shell_text(create_network))
        create_proc = run(create_network, timeout=15)
        evidence_data["create_network"] = create_proc
        if create_proc["returncode"] != 0:
            return {"status": "failed", "detail": "Could not create internal Docker network for credential injection.", "command": "\n".join(commands), "evidence": evidence_data}

        broker_cmd = [
            docker,
            "run",
            "-d",
            "--rm",
            "--name",
            broker,
            "--network",
            network,
            "--network-alias",
            "agent-credential-broker",
            "-v",
            f"{project_root}:/app:ro",
            "-w",
            "/app",
            image,
            "python",
            "backend/credential_broker.py",
            "--handle",
            handle,
            "--secret",
            secret,
        ]
        redacted_broker_cmd = [("[REDACTED_SECRET]" if part == secret else part) for part in broker_cmd]
        commands.append(shell_text(redacted_broker_cmd))
        broker_proc = run(broker_cmd, timeout=20)
        evidence_data["start_broker"] = broker_proc
        if broker_proc["returncode"] != 0:
            return {"status": "failed", "detail": "Could not start credential broker container.", "command": "\n".join(commands), "evidence": evidence_data}

        task_code = r"""
import json
import os
import pathlib
import urllib.request

handle = os.environ["CREDENTIAL_HANDLE"]
broker_url = os.environ["CREDENTIAL_BROKER_URL"]
env_dump = "\n".join(f"{k}={v}" for k, v in os.environ.items())
cmdline_dump = pathlib.Path("/proc/self/cmdline").read_text(errors="replace")
app_files_scanned = 0
app_files_read_errors = 0
for path in pathlib.Path("/app").rglob("*"):
    if path.is_file() and path.stat().st_size <= 200000:
        app_files_scanned += 1
scan = {
    "env_dump": env_dump,
    "cmdline_dump": cmdline_dump,
    "app_files_scanned": app_files_scanned,
    "app_files_read_errors": app_files_read_errors,
}
with urllib.request.urlopen(f"{broker_url}/use?handle={handle}", timeout=8) as response:
    broker_response = json.loads(response.read().decode("utf-8"))
print(json.dumps({"scan": scan, "broker_response": broker_response}, ensure_ascii=False))
"""
        task_cmd = [
            docker,
            "run",
            "--rm",
            "--network",
            network,
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=32m",
            "-v",
            f"{project_root}:/app:ro",
            "-w",
            "/app",
            "-e",
            f"CREDENTIAL_HANDLE={handle}",
            "-e",
            "CREDENTIAL_BROKER_URL=http://agent-credential-broker:18081",
            image,
            "python",
            "-c",
            task_code,
        ]
        commands.append(shell_text(task_cmd))
        task_proc = run(task_cmd, timeout=30)
        evidence_data["task_probe"] = compact_proc(task_proc, limit=5000)

        logs_cmd = [docker, "logs", broker]
        commands.append(shell_text(logs_cmd))
        logs = run(logs_cmd, timeout=10)
        evidence_data["broker_logs"] = compact_proc(logs, limit=5000)

        parsed: dict[str, Any] = {}
        try:
            parsed = json.loads(task_proc["stdout"])
        except Exception as exc:
            evidence_data["parse_error"] = str(exc)

        scan = parsed.get("scan", {}) if isinstance(parsed, dict) else {}
        broker_response = parsed.get("broker_response", {}) if isinstance(parsed, dict) else {}
        output_text = json.dumps(parsed, ensure_ascii=False) + logs["stdout"] + logs["stderr"] + task_proc["stderr"]
        no_plaintext_leak = secret not in output_text
        project_files_contain_secret = False
        for path in project_root.rglob("*"):
            if path.is_file() and path.stat().st_size <= 200000:
                try:
                    if secret in path.read_text(errors="ignore"):
                        project_files_contain_secret = True
                        break
                except Exception:
                    pass
        no_probe_leak = all(secret not in str(scan.get(key, "")) for key in ("env_dump", "cmdline_dump")) and not project_files_contain_secret
        broker_ok = broker_response.get("ok") is True and broker_response.get("credential_result") == "authorized" and broker_response.get("plaintext_secret") is None
        audit_ok = "credential_result" in logs["stdout"] and '"plaintext_secret": null' in logs["stdout"]
        evidence_data["leak_checks"] = {
            "env_contains_plaintext_secret": secret in str(scan.get("env_dump", "")),
            "cmdline_contains_plaintext_secret": secret in str(scan.get("cmdline_dump", "")),
            "project_files_contain_plaintext_secret": project_files_contain_secret,
            "output_contains_plaintext_secret": secret in output_text,
            "broker_returned_plaintext_secret": broker_response.get("plaintext_secret") is not None,
            "app_files_scanned_by_task": scan.get("app_files_scanned", 0),
        }
        ok = task_proc["returncode"] == 0 and broker_ok and no_probe_leak and no_plaintext_leak and audit_ok
        return {
            "status": "passed" if ok else "failed",
            "detail": "Credential handle was usable through the broker while plaintext secret stayed out of task env/cmdline/files/output and broker audit was recorded." if ok else "Credential injection behavior did not match expectations.",
            "command": "\n".join(commands),
            "evidence": evidence_data,
        }
    finally:
        run([docker, "rm", "-f", broker], timeout=10)
        run([docker, "network", "rm", network], timeout=10)


def verify_e2b_like_adapter(project_root: Path, service: Any) -> dict[str, Any]:
    from backend.e2b_adapter import DockerE2BAdapter

    adapter = DockerE2BAdapter(project_root, service)
    emit_progress("session_started", "创建会话式沙箱", "开始执行 create / run / query / destroy 生命周期。", {})
    commands = [
        "GET /api/e2b/capability",
        "POST /api/e2b/sandboxes",
        "POST /api/e2b/sandboxes/{sandbox_id}/run",
        "GET /api/e2b/sandboxes/{sandbox_id}",
        "POST /api/e2b/sandboxes/{sandbox_id}/destroy",
    ]
    capability = adapter.capability()
    session = adapter.create_session({
        "actor": "sales-user",
        "agent": "e2b-like-verification-agent",
        "timeout_seconds": 10,
        "memory_mb": 512,
        "cpu_cores": 1,
        "metadata": {"purpose": "verification"},
    })
    run_result = adapter.run_template(session["id"], {
        "scenario_id": "s19_over_stock_warning",
        "actor": "sales-user",
        "input": {},
    })
    queried = adapter.get_session(session["id"])
    destroyed = adapter.destroy_session(session["id"])
    emit_progress("session_finished", "会话生命周期完成", f"会话 {session['id']} 已运行任务并销毁。", {"session_id": session["id"], "task_id": run_result.get("task_id")})

    task = run_result.get("task", {})
    ok = (
        capability.get("adapter") == "DockerE2BAdapter"
        and session.get("status") == "running"
        and task.get("status") == "success"
        and task.get("executor") == "DockerTemplateExecutor"
        and queried is not None
        and len(queried.get("tasks", [])) >= 1
        and destroyed.get("status") == "destroyed"
    )
    return {
        "status": "passed" if ok else "failed",
        "detail": "E2B-like adapter created a Docker sandbox session, ran a scenario task, exposed session evidence, and destroyed the session." if ok else "E2B-like adapter workflow did not complete.",
        "command": "\n".join(commands),
        "evidence": {
            "capability": capability,
            "session": session,
            "run": run_result.get("run"),
            "task_status": task.get("status"),
            "task_executor": task.get("executor"),
            "task_result": task.get("result"),
            "queried_session": queried,
            "destroyed_session": destroyed,
        },
    }


def verify_hanhe_role_scenario_e2e(service: Any) -> dict[str, Any]:
    payload = {
        "scenario_id": "s19_over_stock_warning",
        "actor": "sales-user",
        "agent": "hanhe-supply-chain-agent",
        "timeout_seconds": 10,
        "memory_mb": 512,
        "cpu_cores": 1,
        "input": {},
    }
    emit_progress("scenario_started", "运行汉和销售/供应链场景", "账号、权限、mock ERP 数据、Docker 执行、成本和审计链路开始运行。", {})
    task = service.create_task(payload)
    result_payload = task.get("result", {}).get("payload", {})
    platform_checks = task.get("platform_checks", {})
    security = platform_checks.get("security_compliance", {})
    account = platform_checks.get("account_gateway", {})
    cost = platform_checks.get("cost_control", {})
    audit_events = platform_checks.get("audit_events", [])
    runtime = task.get("result", {}).get("sandbox_runtime", {})
    logs = [item.get("event") for item in task.get("logs", [])]
    ok = (
        task.get("status") == "success"
        and task.get("executor") == "DockerTemplateExecutor"
        and result_payload.get("inventory") == 50.0
        and result_payload.get("total_order_qty") == 90.0
        and result_payload.get("over_qty") == 40.0
        and result_payload.get("status") == "warning"
        and account.get("role") == "销售员"
        and security.get("allowed") is True
        and runtime.get("executor") == "DockerTemplateExecutor"
        and cost.get("meter") == "mock_cost_control"
        and len(audit_events) >= 2
        and all(event in logs for event in ["sandbox.requested", "security.precheck", "sandbox.result_collected", "sandbox.destroyed"])
    )
    return {
        "status": "passed" if ok else "failed",
        "detail": "Hanhe sales/supply-chain over-stock scenario proved the full module chain end to end." if ok else "Hanhe role scenario did not produce the expected end-to-end evidence.",
        "command": "POST /api/tasks scenario=s19_over_stock_warning actor=sales-user",
        "evidence": {
            "task_id": task.get("id"),
            "scenario": task.get("scenario_name"),
            "actor": task.get("audit", {}).get("actor"),
            "role": account.get("role"),
            "department": account.get("department"),
            "required_permissions": security.get("required_permissions"),
            "missing_permissions": security.get("missing_permissions"),
            "business_result": result_payload,
            "runtime": runtime,
            "cost": cost,
            "audit_event_count": len(audit_events),
            "lifecycle_events": logs,
        },
    }


def verify_hanhe_finance_invoice_e2e(service: Any) -> dict[str, Any]:
    emit_progress("scenario_started", "运行汉和财务核销场景", "财务身份、权限、mock 发票/入库单和 Docker 执行链路开始运行。", {})
    task = service.create_task({
        "scenario_id": "s04_invoice_matching",
        "actor": "demo-user",
        "agent": "hanhe-finance-agent",
        "timeout_seconds": 10,
        "memory_mb": 512,
        "cpu_cores": 1,
        "input": {},
    })
    result_payload = task.get("result", {}).get("payload", {})
    matches = result_payload.get("matches", [])
    platform_checks = task.get("platform_checks", {})
    security = platform_checks.get("security_compliance", {})
    account = platform_checks.get("account_gateway", {})
    cost = platform_checks.get("cost_control", {})
    audit_events = platform_checks.get("audit_events", [])
    runtime = task.get("result", {}).get("sandbox_runtime", {})
    logs = [item.get("event") for item in task.get("logs", [])]
    statuses = {item.get("status") for item in matches}
    ok = (
        task.get("status") == "success"
        and task.get("executor") == "DockerTemplateExecutor"
        and account.get("role") == "财务会计"
        and security.get("allowed") is True
        and "invoice:read" in security.get("required_permissions", [])
        and "receipt:read" in security.get("required_permissions", [])
        and "matched" in statuses
        and "exception" in statuses
        and runtime.get("executor") == "DockerTemplateExecutor"
        and cost.get("meter") == "mock_cost_control"
        and len(audit_events) >= 2
        and all(event in logs for event in ["sandbox.requested", "security.precheck", "mock.data_loaded", "sandbox.result_collected", "sandbox.destroyed"])
    )
    return {
        "status": "passed" if ok else "failed",
        "detail": "Hanhe finance invoice matching scenario proved Docker execution with account, permission, mock ERP, cost, and audit evidence." if ok else "Hanhe finance invoice scenario did not produce the expected evidence.",
        "command": "POST /api/tasks scenario=s04_invoice_matching actor=demo-user",
        "evidence": {
            "task_id": task.get("id"),
            "scenario": task.get("scenario_name"),
            "actor": task.get("audit", {}).get("actor"),
            "role": account.get("role"),
            "department": account.get("department"),
            "required_permissions": security.get("required_permissions"),
            "missing_permissions": security.get("missing_permissions"),
            "business_result": result_payload,
            "runtime": runtime,
            "cost": cost,
            "audit_event_count": len(audit_events),
            "lifecycle_events": logs,
        },
    }


def verify_hanhe_purchase_plan_e2e(service: Any) -> dict[str, Any]:
    emit_progress("scenario_started", "运行汉和采购计划场景", "采购权限、历史采购/库存数据和 Docker 执行链路开始运行。", {})
    task = service.create_task({
        "scenario_id": "s20_purchase_plan",
        "actor": "demo-user",
        "agent": "hanhe-purchase-agent",
        "timeout_seconds": 10,
        "memory_mb": 512,
        "cpu_cores": 1,
        "input": {},
    })
    result_payload = task.get("result", {}).get("payload", {})
    platform_checks = task.get("platform_checks", {})
    security = platform_checks.get("security_compliance", {})
    account = platform_checks.get("account_gateway", {})
    cost = platform_checks.get("cost_control", {})
    audit_events = platform_checks.get("audit_events", [])
    runtime = task.get("result", {}).get("sandbox_runtime", {})
    logs = [item.get("event") for item in task.get("logs", [])]
    ok = (
        task.get("status") == "success"
        and task.get("executor") == "DockerTemplateExecutor"
        and security.get("allowed") is True
        and "purchase:read" in security.get("required_permissions", [])
        and "inventory:read" in security.get("required_permissions", [])
        and float(result_payload.get("forecast_demand", 0)) > float(result_payload.get("current_stock", 0))
        and float(result_payload.get("suggested_purchase", 0)) > 0
        and runtime.get("executor") == "DockerTemplateExecutor"
        and cost.get("meter") == "mock_cost_control"
        and len(audit_events) >= 2
        and all(event in logs for event in ["sandbox.requested", "security.precheck", "mock.data_loaded", "sandbox.result_collected", "sandbox.destroyed"])
    )
    return {
        "status": "passed" if ok else "failed",
        "detail": "Hanhe purchase-plan scenario proved Docker execution with mock ERP purchase data, permissions, cost, and audit evidence." if ok else "Hanhe purchase-plan scenario did not produce the expected evidence.",
        "command": "POST /api/tasks scenario=s20_purchase_plan actor=demo-user",
        "evidence": {
            "task_id": task.get("id"),
            "scenario": task.get("scenario_name"),
            "actor": task.get("audit", {}).get("actor"),
            "role": account.get("role"),
            "department": account.get("department"),
            "required_permissions": security.get("required_permissions"),
            "missing_permissions": security.get("missing_permissions"),
            "business_result": result_payload,
            "runtime": runtime,
            "cost": cost,
            "audit_event_count": len(audit_events),
            "lifecycle_events": logs,
        },
    }


def evidence(status: str, command: list[str], proc: dict[str, Any], detail: str) -> dict[str, Any]:
    return {
        "status": status,
        "detail": detail,
        "command": shell_text(command),
        "evidence": proc,
    }


def run(command: list[str], timeout: int) -> dict[str, Any]:
    command_text = shell_text(command)
    emit_progress("command_started", "执行后端命令", compact_text(command_text, 700), {"command": compact_text(command_text, 1400), "timeout_seconds": timeout})
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        emit_progress("command_timeout", "命令执行超时", f"命令超过 {timeout} 秒，触发超时控制。", {"command": compact_text(command_text, 700), "timeout_seconds": timeout})
        raise
    result = {"returncode": proc.returncode, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()}
    emit_progress(
        "command_finished",
        "命令执行完成",
        f"returncode={proc.returncode}，stdout={compact_text(result['stdout'], 180) or '(empty)'}",
        {
            "command": compact_text(command_text, 1400),
            "timeout_seconds": timeout,
            "returncode": proc.returncode,
            "stdout": compact_text(result["stdout"], 500),
            "stderr": compact_text(result["stderr"], 500),
        },
    )
    return result


def emit_progress(kind: str, title: str, detail: str, data: dict[str, Any]) -> None:
    reporter = _progress_reporter.get()
    if reporter:
        reporter(kind, title, detail, data)


def compact_text(value: str, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + f" ...[省略 {len(text) - limit} 字符]"


def require_docker() -> str:
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("docker command not found")
    return docker


def docker_image(project_root: Path) -> str:
    config = json.loads((project_root / "config.example.json").read_text(encoding="utf-8"))
    return str(config.get("runtime", {}).get("docker_image", "python:3.12-slim"))


def docker_browser_image(project_root: Path) -> str:
    config = json.loads((project_root / "config.example.json").read_text(encoding="utf-8"))
    return str(config.get("runtime", {}).get("browser_image", "agent-sandbox-browser:chromium-local"))


def compact_proc(proc: dict[str, Any], limit: int = 2500) -> dict[str, Any]:
    compacted = dict(proc)
    for key in ("stdout", "stderr"):
        value = str(compacted.get(key, ""))
        if len(value) > limit:
            compacted[key] = value[:limit] + f"\n...[trimmed {len(value) - limit} chars]"
    return compacted


def shell_text(command: list[str]) -> str:
    return " ".join(str(part) for part in command)

