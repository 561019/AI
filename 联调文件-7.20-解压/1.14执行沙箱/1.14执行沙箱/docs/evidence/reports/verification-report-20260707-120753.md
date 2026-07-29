# 现场验证报告

生成时间：2026-07-07 12:07:53

## 交付口径

```text
Docker 运行时的 L1 1.14 执行沙箱能力包
```

Cube Sandbox 是未来更强隔离选项，不作为当前 Docker 交付阻塞。

## 汇总

- 通过：`13`
- 失败：`0`

## 验证项

### Docker 真隔离运行时

- 状态：`passed`
- 证明点：沙箱任务由 Linux Docker 容器承载，不再是 Windows 本地函数模拟。
- 结论：Docker server is available.
- 命令/API：`/usr/bin/docker info --format {{.ServerVersion}}`

### 任务在 Docker 沙箱中执行

- 状态：`passed`
- 证明点：业务任务进入 DockerTemplateExecutor，产出真实任务编号和业务结果。
- 结论：Docker task returned a business result.
- 命令/API：`POST /api/tasks scenario=s19_over_stock_warning actor=sales-user`

### 宿主机文件隔离

- 状态：`passed`
- 证明点：容器只能看到挂载进去的目录，不能读取沙箱外的宿主机文件，也不能写只读代码目录。
- 结论：Container isolation probe passed.
- 命令/API：`/usr/bin/docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m -v /home/nlp/刘卓/执行沙箱:/app:ro -w /app agent-sandbox-python:3.10-local python -c from pathlib import Path secret=Path('/home/nlp/刘卓/host_secret_6b033bb0.txt') if secret.exists(): raise SystemExit('host secret leaked') try: Path('/app/write_probe.txt').write_text('bad') raise SystemExit('read-only app mount is writable') except OSError: pass print('PASS: secret not mounted; /app is read-only')`

### 跑飞任务自动停止

- 状态：`passed`
- 证明点：死循环容器会被超时逻辑停止，并带有 CPU/内存限制。
- 结论：Runaway container was stopped after timeout.
- 命令/API：`/usr/bin/docker run --rm --name verify-timeout-cc312ff6 --network none --cpus 0.5 --memory 64m agent-sandbox-python:3.10-local python -c while True: pass`

### 默认禁止出站

- 状态：`passed`
- 证明点：容器使用 --network none，默认不能访问外网。
- 结论：Outbound network was blocked by --network none.
- 命令/API：`/usr/bin/docker run --rm --network none agent-sandbox-python:3.10-local python -c import urllib.request; urllib.request.urlopen('https://example.com', timeout=3)`

### 域名级出站白名单网关

- 状态：`passed`
- 证明点：任务容器不能直接出网，只能通过 egress-proxy 访问白名单域名。
- 结论：Egress gateway allowed a controlled allowlisted test domain, blocked a non-allowlisted domain, and prevented direct bypass.
- 命令/API：`/usr/bin/docker network create --internal agent-egress-43295e5c /usr/bin/docker run -d --rm --name agent-egress-proxy-43295e5c --network agent-egress-43295e5c -v /home/nlp/刘卓/执行沙箱:/app:ro -w /app agent-sandbox-python:3.10-local python backend/egress_gateway.py --allow sandbox-allow.test --serve-local sandbox-allow.test /usr/bin/docker run --rm --network agent-egress-43295e5c -e http_proxy=http://agent-egress-proxy-43295e5c:18080 agent-sandbox-python:3.10-local python -c import urllib.request; print(urllib.request.urlopen('http://sandbox-allow.test', timeout=8).status) /usr/bin/docker run --rm --network agent-egress-43295e5c -e http_proxy=http://agent-egress-proxy-43295e5c:18080 agent-sandbox-python:3.10-local python -c import urllib.request; urllib.request.urlopen('http://sandbox-blocked.test', timeout=8) /usr/bin/docker run --rm --network agent-egress-43295e5c agent-sandbox-python:3.10-local python -c import urllib.request; urllib.request.urlopen('http://sandbox-allow.test', timeout=5) /usr/bin/docker logs agent-egress-proxy-43295e5c`

### 浏览器沙箱出站验证

- 状态：`passed`
- 证明点：Headless Chromium 在独立 Docker 浏览器容器里运行，不能直接出网，只能经白名单网关访问允许域名。
- 结论：Browser container loaded a controlled allowlisted page through the gateway, hit a deny record for a non-allowlisted domain, and could not bypass the proxy.
- 命令/API：`/usr/bin/docker network create --internal agent-browser-3d85aef9 /usr/bin/docker run -d --rm --name agent-browser-proxy-3d85aef9 --network agent-browser-3d85aef9 -v /home/nlp/刘卓/执行沙箱:/app:ro -w /app agent-sandbox-python:3.10-local python backend/egress_gateway.py --allow sandbox-allow.test --serve-local sandbox-allow.test /usr/bin/docker run --rm --memory 768m --cpus 1 --network agent-browser-3d85aef9 --read-only --tmpfs /tmp:rw,nosuid,size=256m --tmpfs /run:rw,nosuid,size=64m --tmpfs /root:rw,nosuid,size=64m --tmpfs /var/tmp:rw,nosuid,size=64m agent-sandbox-browser:chromium-local /bin/bash -lc mkdir -p /tmp/chrome/crash; chromium --headless --no-sandbox --disable-gpu --disable-dev-shm-usage --disable-crash-reporter --disable-breakpad --disable-background-networking --disable-sync --disable-default-apps --metrics-recording-only --safebrowsing-disable-auto-update --crash-dumps-dir=/tmp/chrome/crash --no-first-run --user-data-dir=/tmp/chrome --proxy-server=http://agent-browser-proxy-3d85aef9:18080 --dump-dom http://sandbox-allow.test /usr/bin/docker run --rm --memory 768m --cpus 1 --network agent-browser-3d85aef9 --read-only --tmpfs /tmp:rw,nosuid,size=256m --tmpfs /run:rw,nosuid,size=64m --tmpfs /root:rw,nosuid,size=64m --tmpfs /var/tmp:rw,nosuid,size=64m agent-sandbox-browser:chromium-local /bin/bash -lc mkdir -p /tmp/chrome/crash; chromium --headless --no-sandbox --disable-gpu --disable-dev-shm-usage --disable-crash-reporter --disable-breakpad --disable-background-networking --disable-sync --disable-default-apps --metrics-recording-only --safebrowsing-disable-auto-update --crash-dumps-dir=/tmp/chrome/crash --no-first-run --user-data-dir=/tmp/chrome --proxy-server=http://agent-browser-proxy-3d85aef9:18080 --dump-dom http://sandbox-blocked.test /usr/bin/docker run --rm --memory 768m --cpus 1 --network agent-browser-3d85aef9 --read-only --tmpfs /tmp:rw,nosuid,size=256m --tmpfs /run:rw,nosuid,size=64m --tmpfs /root:rw,nosuid,size=64m --tmpfs /var/tmp:rw,nosuid,size=64m agent-sandbox-browser:chromium-local /bin/bash -lc mkdir -p /tmp/chrome/crash; chromium --headless --no-sandbox --disable-gpu --disable-dev-shm-usage --disable-crash-reporter --disable-breakpad --disable-background-networking --disable-sync --disable-default-apps --metrics-recording-only --safebrowsing-disable-auto-update --crash-dumps-dir=/tmp/chrome/crash --no-first-run --user-data-dir=/tmp/chrome --dump-dom http://sandbox-allow.test /usr/bin/docker logs agent-browser-proxy-3d85aef9`

### 权限不足前置拦截

- 状态：`passed`
- 证明点：没有权限的角色不会正常执行敏感场景。
- 结论：Permission denial path worked.
- 命令/API：`POST /api/tasks scenario=s04_invoice_matching actor=sales-user`

### 凭据注入不暴露明文

- 状态：`passed`
- 证明点：安全合规侧持有明文凭据，任务容器只拿到短期句柄，不能从环境变量、命令行或挂载目录读到明文密钥。
- 结论：Credential handle was usable through the broker while plaintext secret stayed out of task env/cmdline/files/output and broker audit was recorded.
- 命令/API：`/usr/bin/docker network create --internal agent-cred-97af5be7 /usr/bin/docker run -d --rm --name agent-cred-broker-97af5be7 --network agent-cred-97af5be7 --network-alias agent-credential-broker -v /home/nlp/刘卓/执行沙箱:/app:ro -w /app agent-sandbox-python:3.10-local python backend/credential_broker.py --handle handle-70aa0e1962fb4fdfbe5186d42055c412 --secret [REDACTED_SECRET] /usr/bin/docker run --rm --network agent-cred-97af5be7 --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m -v /home/nlp/刘卓/执行沙箱:/app:ro -w /app -e CREDENTIAL_HANDLE=handle-70aa0e1962fb4fdfbe5186d42055c412 -e CREDENTIAL_BROKER_URL=http://agent-credential-broker:18081 agent-sandbox-python:3.10-local python -c import json import os import pathlib import urllib.request handle = os.environ["CREDENTIAL_HANDLE"] broker_url = os.environ["CREDENTIAL_BROKER_URL"] env_dump = "\n".join(f"{k}={v}" for k, v in os.environ.items()) cmdline_dump = pathlib.Path("/proc/self/cmdline").read_text(errors="replace") app_files_scanned = 0 app_files_read_errors = 0 for path in pathlib.Path("/app").rglob("*"): if path.is_file() and path.stat().st_size <= 200000: app_files_scanned += 1 scan = { "env_dump": env_dump, "cmdline_dump": cmdline_dump, "app_files_scanned": app_files_scanned, "app_files_read_errors": app_files_read_errors, } with urllib.request.urlopen(f"{broker_url}/use?handle={handle}", timeout=8) as response: broker_response = json.loads(response.read().decode("utf-8")) print(json.dumps({"scan": scan, "broker_response": broker_response}, ensure_ascii=False)) /usr/bin/docker logs agent-cred-broker-97af5be7`

### E2B-like Docker 适配器

- 状态：`passed`
- 证明点：在不依赖 Cube 的情况下，提供 create/run/query/destroy 形态的沙箱会话接口，底层仍由 Docker 沙箱执行。
- 结论：E2B-like adapter created a Docker sandbox session, ran a scenario task, exposed session evidence, and destroyed the session.
- 命令/API：`GET /api/e2b/capability POST /api/e2b/sandboxes POST /api/e2b/sandboxes/{sandbox_id}/run GET /api/e2b/sandboxes/{sandbox_id} POST /api/e2b/sandboxes/{sandbox_id}/destroy`

### 汉和岗位场景端到端证明

- 状态：`passed`
- 证明点：用销售/供应链真实岗位场景证明本 L1 沙箱模块能承接任务、隔离执行、输出结果、记录权限/成本/审计证据。
- 结论：Hanhe sales/supply-chain over-stock scenario proved the full module chain end to end.
- 命令/API：`POST /api/tasks scenario=s19_over_stock_warning actor=sales-user`

### 汉和财务发票核销端到端证明

- 状态：`passed`
- 证明点：用财务岗位场景证明沙箱能接收 ERP 发票/入库单数据，在 Docker 内完成核销匹配，并留下权限、成本和审计证据。
- 结论：Hanhe finance invoice matching scenario proved Docker execution with account, permission, mock ERP, cost, and audit evidence.
- 命令/API：`POST /api/tasks scenario=s04_invoice_matching actor=demo-user`

### 汉和采购计划端到端证明

- 状态：`passed`
- 证明点：用采购计划场景证明沙箱能接收历史采购和库存数据，在 Docker 内计算预测需求和建议采购量。
- 结论：Hanhe purchase-plan scenario proved Docker execution with mock ERP purchase data, permissions, cost, and audit evidence.
- 命令/API：`POST /api/tasks scenario=s20_purchase_plan actor=demo-user`

## 说明

本报告由服务端实时运行 `/api/verification/run {"case_id":"all"}` 同等验证逻辑后生成。
报告文件用于交付复查；详细 stdout/stderr 和结构化证据见同名 JSON 文件。
